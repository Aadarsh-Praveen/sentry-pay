"""
agent/feedback_handler.py
─────────────────────────────────────────────────────────────────────────────
Process human feedback on agent verdicts to make the system smarter over time.

Three feedback actions:
  1. confirm_block     → human says agent was right, this IS fraud
                       → flag account in beneficiary_intel (shared across all users)
                       → mark verdict as TRUE_POSITIVE

  2. mark_safe         → human says agent was wrong, this is legitimate
                       → add vendor + account to user_baselines.known_vendors/accounts
                       → mark verdict as FALSE_POSITIVE

  3. confirm_allow     → human confirms agent's ALLOW verdict was right
                       → no-op for indices, just records the confirmation
                       → mark verdict as TRUE_NEGATIVE
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from config.elastic_client import get_client

log = logging.getLogger("sentry-pay.feedback")

EMAIL_VERDICTS_INDEX = "email_verdicts"
BENEFICIARY_INTEL    = "beneficiary_intel"
USER_BASELINES       = "user_baselines"


# ── Feedback actions ─────────────────────────────────────────────────────────
def confirm_block(verdict_id: str, user_id: str, note: Optional[str] = None) -> dict:
    """
    Human confirms a BLOCK verdict was correct (true positive).
    → Flag the account in beneficiary_intel globally (community intelligence)
    → Update email_verdicts with human feedback
    """
    es      = get_client()
    verdict = _get_verdict(verdict_id, user_id)
    account = verdict.get("account_number")
    sender  = verdict.get("sender_domain")

    flagged_count = 0

    # 1. Flag the account globally
    if account:
        try:
            es.update(
                index=BENEFICIARY_INTEL,
                id=account,
                body={
                    "doc": {
                        "account_number":  account,
                        "is_flagged":      True,
                        "risk_score":      0.95,
                        "flag_reason":     f"Confirmed BEC by human reviewer ({note or 'no note'})",
                        "datasets":        ["sentry_pay_community"],
                        "flagged_by_user": user_id,
                        "flagged_at":      datetime.now(timezone.utc).isoformat(),
                    },
                    "doc_as_upsert": True,
                },
                refresh=True,
            )
            flagged_count += 1
            log.info(f"[feedback] Flagged account {account[-4:]} as confirmed fraud")
        except Exception as exc:
            log.error(f"[feedback] Failed to flag account: {exc}")

    # 2. Mark verdict as TRUE_POSITIVE
    _update_verdict_feedback(verdict_id, "CONFIRMED_BLOCK", note)

    return {
        "status":            "confirmed",
        "verdict_id":        verdict_id,
        "accounts_flagged":  flagged_count,
        "community_updated": True,
    }


def mark_safe(verdict_id: str, user_id: str, note: Optional[str] = None) -> dict:
    """
    Human says verdict was wrong (false positive). This is a legit payment.
    → Add vendor + account to user_baselines.known_vendors/accounts
    → Update email_verdicts with human feedback
    """
    es      = get_client()
    verdict = _get_verdict(verdict_id, user_id)
    vendor  = verdict.get("recipient_name")
    account = verdict.get("account_number")

    added_vendor  = False
    added_account = False

    # Add to user_baselines.known_vendors and known_accounts
    if vendor or account:
        try:
            baseline = es.get(index=USER_BASELINES, id=user_id, ignore=[404])
            if baseline.get("found"):
                source = baseline["_source"]
                known_vendors  = list(source.get("known_vendors",  []))
                known_accounts = list(source.get("known_accounts", []))

                if vendor and vendor not in known_vendors:
                    known_vendors.append(vendor)
                    added_vendor = True
                if account and account not in known_accounts:
                    known_accounts.append(account)
                    added_account = True

                if added_vendor or added_account:
                    es.update(
                        index=USER_BASELINES,
                        id=user_id,
                        body={
                            "doc": {
                                "known_vendors":  known_vendors,
                                "known_accounts": known_accounts,
                                "last_updated":   datetime.now(timezone.utc).isoformat(),
                            }
                        },
                        refresh=True,
                    )
                    log.info(f"[feedback] Added vendor={vendor} account={account[-4:] if account else None} to baseline for {user_id}")
        except Exception as exc:
            log.error(f"[feedback] Failed to update baseline: {exc}")

    _update_verdict_feedback(verdict_id, "MARKED_SAFE", note)

    return {
        "status":        "marked_safe",
        "verdict_id":    verdict_id,
        "added_vendor":  added_vendor,
        "added_account": added_account,
    }


def confirm_allow(verdict_id: str, user_id: str) -> dict:
    """Human confirms an ALLOW verdict was correct (true negative)."""
    _update_verdict_feedback(verdict_id, "CONFIRMED_ALLOW", None)
    return {"status": "confirmed", "verdict_id": verdict_id}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _get_verdict(verdict_id: str, user_id: str) -> dict:
    """Fetch a verdict from email_verdicts, ensuring user_id matches."""
    es = get_client()
    resp = es.search(
        index=EMAIL_VERDICTS_INDEX,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"verdict_id": verdict_id}},
                        {"term": {"user_id":    user_id}},
                    ]
                }
            },
            "size": 1,
        },
    )
    hits = resp["hits"]["hits"]
    if not hits:
        raise ValueError(f"Verdict {verdict_id} not found for user {user_id}")
    return hits[0]["_source"]


def _update_verdict_feedback(verdict_id: str, human_verdict: str, note: Optional[str]):
    """Update the email_verdicts index with human feedback."""
    es = get_client()
    try:
        es.update_by_query(
            index=EMAIL_VERDICTS_INDEX,
            body={
                "query":  {"term": {"verdict_id": verdict_id}},
                "script": {
                    "source": """
                        ctx._source.human_verdict    = params.human_verdict;
                        ctx._source.human_feedback   = params.note;
                        ctx._source.learning_applied = true;
                        ctx._source.feedback_at      = params.timestamp;
                    """,
                    "params": {
                        "human_verdict": human_verdict,
                        "note":          note or "",
                        "timestamp":     datetime.now(timezone.utc).isoformat(),
                    },
                },
            },
            refresh=True,
            conflicts="proceed",
        )
    except Exception as exc:
        log.error(f"[feedback] Failed to update verdict feedback: {exc}")


# ── Stats endpoint ───────────────────────────────────────────────────────────
def get_learning_stats(user_id: Optional[str] = None) -> dict:
    """Aggregate feedback statistics — used by /learning/stats endpoint."""
    es = get_client()

    user_filter = [{"term": {"user_id": user_id}}] if user_id else []

    try:
        resp = es.search(
            index=EMAIL_VERDICTS_INDEX,
            body={
                "size": 0,
                "query": {"bool": {"must": user_filter}} if user_filter else {"match_all": {}},
                "aggs": {
                    "by_agent_verdict":   {"terms": {"field": "agent_verdict"}},
                    "by_human_verdict":   {"terms": {"field": "human_verdict",   "missing": "PENDING"}},
                    "feedback_applied":   {"filter": {"term": {"learning_applied": True}}},
                    "total_decisions":    {"value_count": {"field": "verdict_id"}},
                },
            },
        )
    except Exception as exc:
        log.error(f"[feedback] Stats query failed: {exc}")
        return {"error": str(exc)}

    aggs = resp["aggregations"]
    return {
        "total_decisions":   aggs["total_decisions"]["value"],
        "feedback_applied":  aggs["feedback_applied"]["doc_count"],
        "by_agent_verdict":  {b["key"]: b["doc_count"] for b in aggs["by_agent_verdict"]["buckets"]},
        "by_human_verdict":  {b["key"]: b["doc_count"] for b in aggs["by_human_verdict"]["buckets"]},
    }