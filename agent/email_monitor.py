"""
agent/email_monitor.py
─────────────────────────────────────────────────────────────────────────────
Background worker that polls Gmail every N seconds for each user with a
baseline. Analyses new payment-request emails, stores verdicts in Elastic,
auto-generates SAR PDFs for BLOCK verdicts, and labels them in Gmail.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery

from config.elastic_client import get_client
from agent.email_extractor import extract_payment_details
from agent.gmail_client    import fetch_emails_since, apply_label
from agent.sar_generator   import generate_sar

log = logging.getLogger("sentry-pay.monitor")

POLL_INTERVAL  = int(os.getenv("GMAIL_POLL_INTERVAL_SECONDS", "300"))
INDEX_VERDICTS = "email_verdicts"

GCP_PROJECT = os.getenv("GCP_PROJECT_ID")
BQ_DATASET  = os.getenv("BIGQUERY_DATASET", "sentry_pay")
USERS_TABLE = f"{GCP_PROJECT}.{BQ_DATASET}.users"

_stop_event = asyncio.Event()
_last_scan: dict[str, datetime] = {}


def stop():
    _stop_event.set()


def _verdict_doc_id(user_id: str, email_id: str) -> str:
    return hashlib.sha256(f"{user_id}::{email_id}".encode()).hexdigest()[:24]


def _get_users_with_baseline() -> list[dict]:
    bq = bigquery.Client(project=GCP_PROJECT)
    try:
        query = f"""
            SELECT user_id, email
            FROM `{USERS_TABLE}`
            WHERE baseline_built = TRUE
        """
        rows = list(bq.query(query).result())
        return [{"user_id": r.user_id, "email": r.email} for r in rows]
    except Exception as exc:
        log.error(f"[monitor] Failed to list users: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Generate SAR PDF for a BLOCK verdict — called after the verdict is stored
# ─────────────────────────────────────────────────────────────────────────────
def _maybe_generate_sar(decision: dict, details: dict, email: dict, user_id: str) -> str | None:
    """If verdict is BLOCK and sar_required, generate the PDF. Returns sar_pdf_url or None."""
    if decision.get("verdict") != "BLOCK":
        return None
    if not decision.get("sar_required"):
        return None
    try:
        pdf_path = generate_sar(
            decision_id    = decision["decision_id"],
            verdict        = decision,
            email_text     = email.get("body", "")[:5000],
            amount         = float(details.get("amount") or 0),
            recipient_name = details.get("recipient_name") or "unknown",
            account_number = details.get("account_number") or "",
            payment_type   = details.get("payment_type") or "ACH",
            user_id        = user_id,
        )
        if pdf_path:
            log.info(f"[monitor] Generated SAR for decision {decision['decision_id'][:8]}")
            return f"/sar/{decision['decision_id']}"
    except Exception as exc:
        log.warning(f"[monitor] SAR generation failed: {exc}")
    return None


def check_user_now(user_id: str, lookback_minutes: int = 60) -> dict:
    """Analyse new emails for one user since the last scan."""
    last = _last_scan.get(user_id)
    if last is None:
        last = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

    now    = datetime.now(timezone.utc)
    emails = fetch_emails_since(user_id, since=last, max_results=50)

    analysed_count = 0
    blocked_count  = 0

    from agent.gemini_agent import SentryPayAgent
    agent = SentryPayAgent()

    for email in emails:
        try:
            doc_id = _verdict_doc_id(user_id, email["id"])
            if _verdict_exists(doc_id):
                continue

            details = extract_payment_details(email)
            if not details.get("contains_payment_request") or details.get("is_confirmation"):
                continue
            if not details.get("amount") or details["amount"] <= 0:
                continue

            decision = agent.analyse(
                email_text     = email["body"][:3000],
                amount         = float(details["amount"]),
                recipient_name = details.get("recipient_name") or "unknown",
                account_number = details.get("account_number") or "",
                payment_type   = details.get("payment_type") or "ACH",
                user_id        = user_id,
                verbose        = False,
            )

            # Generate SAR PDF for BLOCK verdicts
            sar_url = _maybe_generate_sar(decision, details, email, user_id)

            # Store verdict (including sar_pdf_url)
            _store_verdict(user_id, email, details, decision, sar_url)

            try:
                apply_label(user_id, email["id"], decision["verdict"])
            except Exception as exc:
                log.warning(f"[monitor] Label apply failed: {exc}")

            analysed_count += 1
            if decision["verdict"] == "BLOCK":
                blocked_count += 1
            log.info(f"[monitor] User {user_id}: '{email.get('subject', '')[:40]}' -> {decision['verdict']}")

        except Exception as exc:
            log.error(f"[monitor] Analysis failed for email {email.get('id')}: {exc}")
            continue

    _last_scan[user_id] = now
    return {
        "user_id":         user_id,
        "scanned_since":   last.isoformat(),
        "emails_found":    len(emails),
        "emails_analysed": analysed_count,
        "blocked":         blocked_count,
    }


async def monitor_loop():
    log.info(f"[monitor] Started email monitor interval {POLL_INTERVAL}s")
    while not _stop_event.is_set():
        try:
            users = _get_users_with_baseline()
            for user in users:
                user_id = user.get("user_id")
                if not user_id:
                    continue
                try:
                    result = check_user_now(user_id, lookback_minutes=10)
                    if result["emails_analysed"]:
                        log.info(f"[monitor] User {user_id}: {result['emails_analysed']} analysed, {result['blocked']} blocked")
                except Exception as exc:
                    log.error(f"[monitor] User {user_id} check failed: {exc}")
        except Exception as exc:
            log.error(f"[monitor] Loop iteration failed: {exc}")

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass

    log.info("[monitor] Email monitor stopped")


def _verdict_exists(doc_id: str) -> bool:
    es = get_client()
    if not es.indices.exists(index=INDEX_VERDICTS):
        return False
    try:
        return bool(es.exists(index=INDEX_VERDICTS, id=doc_id))
    except Exception:
        return False


def _store_verdict(user_id: str, email: dict, details: dict, decision: dict, sar_url: str | None = None):
    es = get_client()
    doc_id = _verdict_doc_id(user_id, email["id"])
    try:
        es.index(
            index=INDEX_VERDICTS,
            id=doc_id,
            document={
                "verdict_id":       doc_id,
                "user_id":          user_id,
                "email_id":         email["id"],
                "email_subject":    email.get("subject", ""),
                "sender":           email.get("sender_email", ""),
                "sender_domain":    details.get("sender_domain"),
                "amount":           float(details.get("amount") or 0),
                "recipient_name":   details.get("recipient_name"),
                "account_number":   details.get("account_number"),
                "agent_verdict":    decision["verdict"],
                "agent_confidence": decision.get("confidence", 0.5),
                "human_verdict":    None,
                "typology_matched": decision.get("typology_matched"),
                "decision_id":      decision.get("decision_id"),
                "timestamp":        email.get("date") or datetime.now(timezone.utc).isoformat(),
                "sar_generated":    bool(sar_url),
                "sar_pdf_url":      sar_url,
                "learning_applied": False,
            },
            refresh=True,
        )
    except Exception as exc:
        log.error(f"[monitor] Failed to store verdict: {exc}")