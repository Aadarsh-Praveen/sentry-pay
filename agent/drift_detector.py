"""
SentryPay — Automated Drift Detection
=======================================
Weekly job that analyses the BigQuery decisions table to detect
when agent accuracy is degrading (model drift).

Triggered by:
    Cloud Scheduler → POST /analysis/drift every Sunday 4 AM UTC

What it checks:
    1. Confidence trend — is avg confidence dropping week over week?
    2. Typology hit rate — which fraud patterns are being matched less?
    3. False positive spike — are BLOCK verdicts increasing on legit payments?
    4. Token usage trend — is Gemini using more tokens (sign of confusion)?

Alert thresholds:
    - Avg confidence drop > 10% week over week → WARNING
    - Any typology hit rate drops below 0.60 → ALERT (typology needs refresh)
    - Token usage increases > 30% → INVESTIGATE (prompt may be less clear)

Output:
    Drift report saved to data/processed/drift_report.json
    Console output with recommendations

Usage (local):
    python agent/drift_detector.py

Usage (via API — triggered by Cloud Scheduler):
    POST /analysis/drift
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()
init(autoreset=True)

GCP_PROJECT      = os.getenv("GCP_PROJECT_ID")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "sentry_pay")
TABLE_DECISIONS  = os.getenv("BIGQUERY_TABLE_DECISIONS", "decisions")

# Alert thresholds
CONFIDENCE_DROP_THRESHOLD  = 0.10   # 10% drop triggers warning
TYPOLOGY_HIT_THRESHOLD     = 0.60   # below 60% match rate → refresh typology
TOKEN_INCREASE_THRESHOLD   = 0.30   # 30% more tokens → investigate


def get_bigquery_client():
    """Return an authenticated BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client(project=GCP_PROJECT)


def query_weekly_stats(client, week_offset: int = 0) -> dict:
    """
    Query aggregate stats for a given week.

    Args:
        client: BigQuery client
        week_offset (int): 0 = current week, 1 = last week, 2 = two weeks ago

    Returns:
        dict: weekly statistics
    """
    query = f"""
        SELECT
            COUNT(*)                                    AS total_decisions,
            AVG(confidence)                             AS avg_confidence,
            COUNTIF(verdict = 'BLOCK')                  AS block_count,
            COUNTIF(verdict = 'FRICTION')               AS friction_count,
            COUNTIF(verdict = 'ALLOW')                  AS allow_count,
            AVG(total_tokens)                           AS avg_tokens,
            AVG(processing_ms)                          AS avg_latency_ms
        FROM `{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}`
        WHERE decision_date >= TIMESTAMP_SUB(
            CURRENT_TIMESTAMP(),
            INTERVAL {(week_offset + 1) * 7} DAY
        )
        AND decision_date < TIMESTAMP_SUB(
            CURRENT_TIMESTAMP(),
            INTERVAL {week_offset * 7} DAY
        )
    """
    rows = list(client.query(query).result())
    if not rows:
        return {}

    row = rows[0]
    return {
        "total":       row.total_decisions,
        "avg_conf":    float(row.avg_confidence or 0),
        "block":       row.block_count,
        "friction":    row.friction_count,
        "allow":       row.allow_count,
        "avg_tokens":  float(row.avg_tokens or 0),
        "avg_latency": float(row.avg_latency_ms or 0)
    }


def query_typology_stats(client) -> list:
    """
    Query match rate and avg confidence per typology for the last 7 days.

    Returns:
        list[dict]: typology performance data
    """
    query = f"""
        SELECT
            typology_matched,
            COUNT(*)            AS match_count,
            AVG(confidence)     AS avg_confidence
        FROM `{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}`
        WHERE decision_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
        AND typology_matched IS NOT NULL
        GROUP BY typology_matched
        HAVING COUNT(*) >= 3
        ORDER BY avg_confidence ASC
    """
    rows = list(client.query(query).result())
    return [
        {
            "typology":   row.typology_matched,
            "count":      row.match_count,
            "avg_conf":   float(row.avg_confidence or 0)
        }
        for row in rows
    ]


def analyse_drift() -> dict:
    """
    Run full drift analysis comparing current week vs previous week.

    Compares key metrics between the current 7-day window and the
    previous 7-day window to detect statistically significant changes
    that suggest the agent's behaviour has shifted.

    Returns:
        dict: drift report with alerts, warnings, and recommendations
    """
    print(Fore.CYAN + "\n SentryPay: Drift Analysis \n")
    print(f"  Running at: {datetime.now().isoformat()}")

    try:
        client = get_bigquery_client()
    except Exception as e:
        return {"error": f"BigQuery connection failed: {e}"}

    # Get this week and last week stats
    this_week = query_weekly_stats(client, week_offset=0)
    last_week = query_weekly_stats(client, week_offset=1)
    typologies = query_typology_stats(client)

    if not this_week.get("total"):
        return {
            "status":  "INSUFFICIENT_DATA",
            "message": "Not enough decisions this week for drift analysis",
            "min_required": 10
        }

    alerts   = []
    warnings = []
    info     = []

    # ── Check 1: Confidence trend ─────────────────────────────────────────────
    if last_week.get("avg_conf") and this_week.get("avg_conf"):
        conf_change = this_week["avg_conf"] - last_week["avg_conf"]
        conf_pct    = conf_change / max(last_week["avg_conf"], 0.01)

        if conf_pct < -CONFIDENCE_DROP_THRESHOLD:
            alerts.append({
                "type":    "CONFIDENCE_DROP",
                "message": f"Avg confidence dropped {abs(conf_pct):.0%} "
                           f"({last_week['avg_conf']:.3f} → {this_week['avg_conf']:.3f})",
                "action":  "Review system prompt and check for Gemini model updates"
            })
        else:
            info.append(f"Confidence stable: {this_week['avg_conf']:.3f} "
                       f"(last week: {last_week['avg_conf']:.3f})")

    # ── Check 2: Typology hit rate ─────────────────────────────────────────────
    for typology in typologies:
        if typology["avg_conf"] < TYPOLOGY_HIT_THRESHOLD:
            warnings.append({
                "type":    "LOW_TYPOLOGY_CONFIDENCE",
                "message": f"'{typology['typology']}' avg confidence: "
                           f"{typology['avg_conf']:.3f} (threshold: {TYPOLOGY_HIT_THRESHOLD})",
                "action":  "Consider refreshing this typology's embeddings"
            })

    # ── Check 3: Token usage trend ─────────────────────────────────────────────
    if last_week.get("avg_tokens") and this_week.get("avg_tokens"):
        token_change = (this_week["avg_tokens"] - last_week["avg_tokens"]) \
                       / max(last_week["avg_tokens"], 1)

        if token_change > TOKEN_INCREASE_THRESHOLD:
            warnings.append({
                "type":    "TOKEN_INCREASE",
                "message": f"Avg tokens increased {token_change:.0%} "
                           f"({last_week['avg_tokens']:.0f} → {this_week['avg_tokens']:.0f})",
                "action":  "Review system prompt for clarity and length"
            })

    # ── Check 4: Verdict distribution shift ───────────────────────────────────
    if this_week.get("total") and last_week.get("total"):
        this_block_rate = this_week["block"] / max(this_week["total"], 1)
        last_block_rate = last_week["block"] / max(last_week["total"], 1)

        if abs(this_block_rate - last_block_rate) > 0.20:
            warnings.append({
                "type":    "VERDICT_DISTRIBUTION_SHIFT",
                "message": f"BLOCK rate changed significantly: "
                           f"{last_block_rate:.0%} → {this_block_rate:.0%}",
                "action":  "Review recent cases for false positives or missed frauds"
            })

    # ── Determine overall status ──────────────────────────────────────────────
    if alerts:
        status = "ALERT"
        colour = Fore.RED
    elif warnings:
        status = "WARNING"
        colour = Fore.YELLOW
    else:
        status = "HEALTHY"
        colour = Fore.GREEN

    # ── Print report ──────────────────────────────────────────────────────────
    print(f"\n  {colour}Status: {status}{Style.RESET_ALL}")
    print(f"\n  This week: {this_week.get('total', 0)} decisions")
    print(f"  Last week: {last_week.get('total', 0)} decisions")

    if alerts:
        print(Fore.RED + "\n  ALERTS:")
        for a in alerts:
            print(f"    ✗ {a['message']}")
            print(f"      → {a['action']}")

    if warnings:
        print(Fore.YELLOW + "\n  WARNINGS:")
        for w in warnings:
            print(f"    ⚠ {w['message']}")
            print(f"      → {w['action']}")

    if info:
        print(Fore.GREEN + "\n  INFO:")
        for i in info:
            print(f"    ✓ {i}")

    report = {
        "status":       status,
        "generated_at": datetime.now().isoformat(),
        "this_week":    this_week,
        "last_week":    last_week,
        "typologies":   typologies,
        "alerts":       alerts,
        "warnings":     warnings,
        "info":         info
    }

    # Save report
    output = Path("data/processed/drift_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w') as f:
        json.dump(report, f, indent=2, default=str)

    print(Fore.CYAN + f"\n  Report saved: {output}")
    print(Fore.CYAN + "\n Drift analysis complete. \n")

    return report


if __name__ == "__main__":
    analyse_drift()