"""
SentryPay — Step 5: Synthetic Transaction Generation
=====================================================
Generates realistic 90-day payment histories for three demo user
personas and computes their behavioral baselines. This data is used
by the agent's velocity check to determine whether an incoming
payment is anomalous for that specific user.

Why synthetic data:
    Real customer bank transaction data cannot be used in a public
    demo or open-source repository due to privacy regulations.
    Synthetic data generated with realistic statistical properties
    serves the same purpose without any compliance risk.

Three demo personas:
    demo_user_001 — Sarah Chen, Finance Manager at a construction SMB.
                    Regular payments to 5 known vendors, avg ~$8,500.
    demo_user_002 — James Okafor, SMB owner in import/export.
                    Higher value payments, avg ~$23,000.
    demo_user_003 — Maria Santos, Accounts Payable at a retail chain.
                    Mid-range regular vendor payments, avg ~$13,000.

Baseline computation (IQR method):
    Raw transaction amounts include occasional outliers (unusually
    large or small one-off payments). Computing the mean directly
    would skew the baseline. Instead, outliers are removed using
    the Interquartile Range (IQR) method before computing the mean,
    standard deviation, and the max_normal threshold.

    max_normal = Q3 + (1.5 × IQR)

    Any incoming payment above max_normal triggers the anomaly flag
    in the agent's velocity check.

Output:
    data/processed/customer_transactions.json  (153 records)
    data/processed/user_baselines.json         (3 user profiles)

Usage:
    python data_pipeline/step5_generate_synthetic_transactions.py
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

PROCESSED_DIR     = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

TRANSACTIONS_FILE = PROCESSED_DIR / "customer_transactions.json"
BASELINES_FILE    = PROCESSED_DIR / "user_baselines.json"

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)


# ── Demo user profiles ────────────────────────────────────────────────────────

DEMO_USERS = [
    {
        "user_id":   "demo_user_001",
        "name":      "Sarah Chen",
        "role":      "Finance Manager — Construction SMB",
        "profile":   "regular_smb",
        "currency":  "USD",
        "vendors": [
            {"name": "Apex Scaffolding Ltd",      "account": "GB29NWBK60161331926819", "routing": "026009593", "avg": 12000, "freq": 0.30},
            {"name": "City Office Supplies",       "account": "GB82WEST12345698765432", "routing": "021000021", "avg": 820,   "freq": 0.25},
            {"name": "BuildRight Materials Inc",   "account": "GB33BUKB20201555555555", "routing": "011000138", "avg": 6500,  "freq": 0.20},
            {"name": "Hallmark Payroll Services",  "account": "GB76LOYD30114900000000", "routing": "044000037", "avg": 28000, "freq": 0.15},
            {"name": "MetroCity Insurance Group",  "account": "GB06NWBK60161331926820", "routing": "061000227", "avg": 4200,  "freq": 0.10},
        ]
    },
    {
        "user_id":   "demo_user_002",
        "name":      "James Okafor",
        "role":      "SMB Owner — Import/Export",
        "profile":   "high_value_smb",
        "currency":  "USD",
        "vendors": [
            {"name": "Pacific Rim Trading Co",     "account": "US12345678901234567890", "routing": "021000021", "avg": 45000, "freq": 0.35},
            {"name": "Freightline Logistics",      "account": "US09876543210987654321", "routing": "026009593", "avg": 8500,  "freq": 0.30},
            {"name": "Delta Customs Brokers",      "account": "US11223344556677889900", "routing": "011000138", "avg": 3200,  "freq": 0.20},
            {"name": "First National Payroll",     "account": "US99887766554433221100", "routing": "044000037", "avg": 52000, "freq": 0.15},
        ]
    },
    {
        "user_id":   "demo_user_003",
        "name":      "Maria Santos",
        "role":      "Accounts Payable — Retail Chain",
        "profile":   "retail_smb",
        "currency":  "USD",
        "vendors": [
            {"name": "Sunrise Merchandise Ltd",    "account": "US12121212121212121212", "routing": "061000227", "avg": 22000, "freq": 0.40},
            {"name": "CleanPro Janitorial",        "account": "US34343434343434343434", "routing": "026009593", "avg": 1800,  "freq": 0.25},
            {"name": "SignCraft Display Co",        "account": "US56565656565656565656", "routing": "021000021", "avg": 4500,  "freq": 0.20},
            {"name": "Secure Guard Services",      "account": "US78787878787878787878", "routing": "011000138", "avg": 9500,  "freq": 0.15},
        ]
    }
]


# ── Transaction generation ────────────────────────────────────────────────────

PAYMENT_TYPES    = ["ACH", "Wire", "RTP", "Zelle", "Check"]
PAYMENT_TYPE_PROBS = [0.50, 0.25, 0.10, 0.10, 0.05]

MEMO_TEMPLATES = [
    "Invoice #{inv} — {month} services",
    "Payment for PO-{po}",
    "{month} retainer",
    "Ref: {inv} — as agreed",
    "Monthly settlement {month}",
    "Services rendered — {month}",
]


def random_amount(avg: float) -> float:
    """
    Generate a realistic payment amount centered around an average.

    Uses a lognormal distribution rather than a normal distribution
    because real-world payment amounts are right-skewed — occasional
    large payments exist but most payments cluster around a typical
    value. This produces more realistic transaction data than simple
    random variation around the mean.

    Args:
        avg (float): target average payment amount in USD

    Returns:
        float: a realistic payment amount rounded to 2 decimal places
    """
    # Lognormal gives right-skewed distribution (like real payments)
    sigma  = 0.15
    mu     = np.log(avg) - (sigma**2 / 2)
    amount = np.random.lognormal(mu, sigma)
    return round(max(amount, 50.0), 2)


def random_memo() -> str:
    template = random.choice(MEMO_TEMPLATES)
    return template.format(
        inv   = f"{random.randint(1000, 9999)}",
        po    = f"{random.randint(10000, 99999)}",
        month = datetime.now().strftime("%b %Y")
    )


def generate_transactions_for_user(user: dict, n_days: int = 90) -> list:
    """Generate n_days of transaction history for one user."""
    transactions = []
    vendors      = user['vendors']
    start_date   = datetime.now() - timedelta(days=n_days)

    # Generate ~3-7 transactions per week
    current = start_date
    while current <= datetime.now():
        # Some days have transactions, some don't
        if random.random() < 0.45:  # ~45% of days have at least one transaction
            n_txn_today = random.choices([1, 2, 3], weights=[0.70, 0.25, 0.05])[0]

            for _ in range(n_txn_today):
                # Pick vendor by frequency
                vendor = random.choices(vendors, weights=[v['freq'] for v in vendors])[0]

                transaction = {
                    "transaction_id": uuid.uuid4().hex,
                    "user_id":        user['user_id'],
                    "date":           current.strftime("%Y-%m-%d"),
                    "amount":         random_amount(vendor['avg']),
                    "recipient_name": vendor['name'],
                    "account_number": vendor['account'],
                    "routing_number": vendor['routing'],
                    "payment_type":   random.choices(PAYMENT_TYPES, weights=PAYMENT_TYPE_PROBS)[0],
                    "memo":           random_memo(),
                    "is_anomalous":   False
                }
                transactions.append(transaction)

        current += timedelta(days=1)

    return transactions


# ── Baseline computation (with IQR outlier removal) ──────────────────────────

def compute_clean_baseline(user_id: str, transactions: list) -> dict:
    """
    Compute a behavioral payment baseline for one user.

    Removes statistical outliers using the IQR method before computing
    baseline metrics. This prevents a single unusually large legitimate
    payment from inflating the baseline and causing the agent to miss
    genuinely anomalous payments in the future.

    Metrics computed:
        mean_payment   — average payment amount after outlier removal
        std_payment    — standard deviation of payment amounts
        p95_payment    — 95th percentile (covers most normal payments)
        max_normal     — IQR upper fence, the anomaly detection threshold
        known_accounts — list of accounts this user has paid before
        known_vendors  — list of vendor names this user has paid before
        preferred_rail — most frequently used payment method

    Args:
        user_id (str): identifier for the user
        transactions (list[dict]): all transactions for this user

    Returns:
        dict: behavioral baseline profile for use in velocity checks
    """
    df = pd.DataFrame(transactions)

    if df.empty or len(df) < 5:
        return {}

    amounts = df['amount'].values

    # IQR outlier removal
    Q1  = np.percentile(amounts, 25)
    Q3  = np.percentile(amounts, 75)
    IQR = Q3 - Q1
    clean = amounts[(amounts >= Q1 - 1.5 * IQR) & (amounts <= Q3 + 1.5 * IQR)]

    outliers_removed = len(amounts) - len(clean)

    baseline = {
        "user_id":         user_id,
        "mean_payment":    float(np.mean(clean)),
        "std_payment":     float(np.std(clean)),
        "median_payment":  float(np.median(clean)),
        "p95_payment":     float(np.percentile(clean, 95)),
        "p99_payment":     float(np.percentile(clean, 99)),
        "max_normal":      float(Q3 + 1.5 * IQR),           # IQR upper bound
        "min_payment":     float(np.min(clean)),
        "total_txns":      int(len(amounts)),
        "outliers_removed": int(outliers_removed),
        "known_accounts":  df['account_number'].unique().tolist(),
        "known_vendors":   df['recipient_name'].unique().tolist(),
        "preferred_rail":  df['payment_type'].mode().iloc[0] if not df.empty else "ACH",
        "computed_at":     datetime.now().isoformat()
    }

    return baseline


# ── EDA on generated transactions ────────────────────────────────────────────

def print_eda(user: dict, df: pd.DataFrame, baseline: dict):
    """Print EDA summary for one user."""
    print(f"\n  {Fore.CYAN}{user['name']} ({user['user_id']}){Style.RESET_ALL}")
    print(f"    Transactions:   {len(df)}")
    print(f"    Amount mean:    ${baseline.get('mean_payment', 0):,.0f}")
    print(f"    Amount std:     ${baseline.get('std_payment', 0):,.0f}")
    print(f"    p95:            ${baseline.get('p95_payment', 0):,.0f}")
    print(f"    Max normal:     ${baseline.get('max_normal', 0):,.0f}  ← anything above this is anomalous")
    print(f"    Outliers removed: {baseline.get('outliers_removed', 0)}")
    print(f"    Known accounts: {len(baseline.get('known_accounts', []))}")
    print(f"    Preferred rail: {baseline.get('preferred_rail', '?')}")

    # Vendor breakdown
    vendor_totals = df.groupby('recipient_name')['amount'].sum().sort_values(ascending=False)
    print(f"\n    Top vendors by total spend:")
    for name, total in vendor_totals.head(4).items():
        print(f"      {name}: ${total:,.0f}")


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    print(Fore.CYAN + "\n SentryPay: Step 5 — Synthetic Transactions \n")

    all_transactions = []
    all_baselines    = []

    for user in DEMO_USERS:
        transactions = generate_transactions_for_user(user, n_days=90)
        df           = pd.DataFrame(transactions)
        baseline     = compute_clean_baseline(user['user_id'], transactions)

        all_transactions.extend(transactions)
        all_baselines.append(baseline)

        print_eda(user, df, baseline)

    # Overall stats
    df_all = pd.DataFrame(all_transactions)
    print(Fore.CYAN + f"\n Overall stats \n")
    print(f"  Total transactions: {Fore.GREEN}{len(all_transactions):,}")
    print(f"  Date range: {df_all['date'].min()} → {df_all['date'].max()}")
    print(f"  Payment type breakdown:")
    for pt, count in df_all['payment_type'].value_counts().items():
        print(f"    {pt}: {count} ({count/len(df_all)*100:.0f}%)")
    print(f"  Amount range: ${df_all['amount'].min():,.0f} → ${df_all['amount'].max():,.0f}")

    # Verify distributions look realistic
    print(Fore.CYAN + "\n Validation checks \n")

    df_user1 = df_all[df_all['user_id'] == 'demo_user_001']
    daily_counts = df_user1.groupby('date').size()
    print(f"  demo_user_001 — avg transactions per active day: "
          f"{daily_counts[daily_counts > 0].mean():.1f}")

    # Save
    with open(TRANSACTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_transactions, f, indent=2, ensure_ascii=False)

    with open(BASELINES_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_baselines, f, indent=2, ensure_ascii=False)

    print(f"\n  Transactions saved: {Fore.GREEN}{TRANSACTIONS_FILE} ({len(all_transactions):,} records)")
    print(f"  Baselines saved:    {Fore.GREEN}{BASELINES_FILE} ({len(all_baselines)} users)")

    print(Fore.CYAN + "\n Step 5 Complete. \n")


if __name__ == "__main__":
    run()