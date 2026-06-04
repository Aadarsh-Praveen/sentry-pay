"""
agent/history_builder.py
─────────────────────────────────────────────────────────────────────────────
Build a real user baseline from 90 days of Gmail history.
Now also auto-generates SAR PDFs for BLOCK verdicts.
"""

from __future__ import annotations

import hashlib
import logging
import statistics
import uuid
from datetime import datetime, timezone
from typing import Optional

from config.elastic_client import get_client
from agent.auth            import mark_baseline_built
from agent.email_extractor import extract_payment_details
from agent.gmail_client    import fetch_emails_for_history, apply_label
from agent.sar_generator   import generate_sar

log = logging.getLogger("sentry-pay.history_builder")

INDEX_TRANSACTIONS = "customer_transactions"
INDEX_BASELINES    = "user_baselines"
INDEX_VERDICTS     = "email_verdicts"


class BuildProgress:
    def __init__(self):
        self.status:           str = "idle"
        self.message:          str = ""
        self.emails_found:     int = 0
        self.emails_processed: int = 0
        self.transactions:     int = 0
        self.verdicts:         int = 0
        self.blocked_count:    int = 0
        self.error:            Optional[str] = None
        self.started_at:       Optional[str] = None
        self.completed_at:     Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


_progress: dict[str, BuildProgress] = {}


def get_progress(user_id: str) -> dict:
    if user_id not in _progress:
        return BuildProgress().to_dict()
    return _progress[user_id].to_dict()


def _verdict_doc_id(user_id: str, email_id: str) -> str:
    return hashlib.sha256(f"{user_id}::{email_id}".encode()).hexdigest()[:24]


def _maybe_generate_sar(decision: dict, details: dict, email: dict, user_id: str) -> str | None:
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
            log.info(f"[history_builder] Generated SAR for decision {decision['decision_id'][:8]}")
            return f"/sar/{decision['decision_id']}"
    except Exception as exc:
        log.warning(f"[history_builder] SAR generation failed: {exc}")
    return None


def build_baseline(user_id: str, days: int = 90) -> dict:
    progress = BuildProgress()
    _progress[user_id] = progress
    progress.status     = "scanning"
    progress.started_at = datetime.now(timezone.utc).isoformat()
    progress.message    = f"Scanning Gmail for the last {days} days..."

    _delete_user_verdicts(user_id)

    try:
        emails = fetch_emails_for_history(user_id, days=days)
        progress.emails_found = len(emails)
        progress.message      = f"Found {len(emails)} emails. Extracting payment details..."
        log.info(f"[history_builder] User {user_id}: {len(emails)} emails to process")

        if not emails:
            progress.status       = "complete"
            progress.completed_at = datetime.now(timezone.utc).isoformat()
            progress.message      = "No payment emails found in the last 90 days."
            _seed_empty_baseline(user_id)
            mark_baseline_built(user_id)
            return progress.to_dict()

        progress.status  = "extracting"
        transactions     = []
        payment_requests = []

        for i, email in enumerate(emails, start=1):
            try:
                details = extract_payment_details(email)
                progress.emails_processed = i
                progress.message = f"Reading emails... {i}/{len(emails)}"

                if not details.get("amount") or details["amount"] <= 0:
                    continue

                if details.get("contains_payment_request") and not details.get("is_confirmation"):
                    payment_requests.append({"email": email, "details": details})

                if details.get("contains_payment_request") or details.get("is_confirmation"):
                    transactions.append({
                        "user_id":         user_id,
                        "transaction_id":  f"gmail_{email['id']}",
                        "timestamp":       email["date"],
                        "amount":          float(details["amount"]),
                        "currency":        details.get("currency") or "USD",
                        "recipient_name":  details.get("recipient_name") or "unknown",
                        "account_number":  details.get("account_number") or "",
                        "payment_type":    details.get("payment_type") or "ACH",
                        "sender_email":    email.get("sender_email", ""),
                        "sender_domain":   details.get("sender_domain"),
                        "source":          "gmail",
                        "email_subject":   email.get("subject", ""),
                        "email_snippet":   email.get("snippet", "")[:200],
                        "is_confirmation": bool(details.get("is_confirmation", False)),
                    })
            except Exception as exc:
                log.warning(f"[history_builder] Extraction failed for email {email.get('id')}: {exc}")
                continue

        progress.transactions = len(transactions)
        progress.message      = f"Extracted {len(transactions)} transactions, {len(payment_requests)} payment requests."

        progress.status = "indexing"
        _bulk_index_transactions(user_id, transactions)

        progress.status  = "computing_baseline"
        progress.message = "Computing your payment patterns..."
        baseline = _compute_baseline(user_id, transactions)
        _index_baseline(user_id, baseline)

        progress.status  = "analysing"
        progress.message = f"Analysing {len(payment_requests)} payment requests..."

        from agent.gemini_agent import SentryPayAgent
        agent = SentryPayAgent()

        for i, item in enumerate(payment_requests, start=1):
            email   = item["email"]
            details = item["details"]
            try:
                decision = agent.analyse(
                    email_text     = email["body"][:3000],
                    amount         = float(details["amount"]),
                    recipient_name = details.get("recipient_name") or "unknown",
                    account_number = details.get("account_number") or "",
                    payment_type   = details.get("payment_type") or "ACH",
                    user_id        = user_id,
                    verbose        = False,
                )

                # Generate SAR PDF if BLOCK
                sar_url = _maybe_generate_sar(decision, details, email, user_id)

                _store_verdict(user_id, email, details, decision, sar_url)

                try:
                    apply_label(user_id, email["id"], decision["verdict"])
                except Exception as exc:
                    log.warning(f"[history_builder] Label apply failed: {exc}")

                progress.verdicts = i
                if decision["verdict"] == "BLOCK":
                    progress.blocked_count += 1
                progress.message = (
                    f"Analysing... {i}/{len(payment_requests)} "
                    f"({progress.blocked_count} blocked)"
                )
                log.info(f"[history_builder] Email '{email.get('subject', '')[:40]}' -> {decision['verdict']}")
            except Exception as exc:
                log.warning(f"[history_builder] Fraud analysis failed for {email.get('id')}: {exc}")
                continue

        mark_baseline_built(user_id)
        progress.status       = "complete"
        progress.completed_at = datetime.now(timezone.utc).isoformat()
        progress.message      = (
            f"Done. {len(transactions)} transactions analysed, "
            f"{progress.blocked_count} flagged as fraud."
        )
        return progress.to_dict()

    except Exception as exc:
        log.error(f"[history_builder] Build failed for user {user_id}: {exc}", exc_info=True)
        progress.status       = "error"
        progress.error        = str(exc)
        progress.completed_at = datetime.now(timezone.utc).isoformat()
        progress.message      = f"Build failed: {exc}"
        return progress.to_dict()


def _delete_user_verdicts(user_id: str):
    es = get_client()
    if not es.indices.exists(index=INDEX_VERDICTS):
        return
    try:
        result = es.delete_by_query(
            index=INDEX_VERDICTS,
            body={"query": {"term": {"user_id": user_id}}},
            refresh=True,
            conflicts="proceed",
        )
        deleted = result.get("deleted", 0)
        if deleted:
            log.info(f"[history_builder] Deleted {deleted} prior verdicts for user {user_id}")
    except Exception as exc:
        log.warning(f"[history_builder] delete_user_verdicts failed: {exc}")


def _store_verdict(user_id: str, email: dict, details: dict, decision: dict, sar_url: str | None = None):
    es = get_client()

    if not es.indices.exists(index=INDEX_VERDICTS):
        es.indices.create(
            index=INDEX_VERDICTS,
            body={
                "mappings": {
                    "properties": {
                        "verdict_id":       {"type": "keyword"},
                        "user_id":          {"type": "keyword"},
                        "email_id":         {"type": "keyword"},
                        "email_subject":    {"type": "text"},
                        "sender":           {"type": "keyword"},
                        "sender_domain":    {"type": "keyword"},
                        "amount":           {"type": "double"},
                        "recipient_name":   {"type": "keyword"},
                        "account_number":   {"type": "keyword"},
                        "agent_verdict":    {"type": "keyword"},
                        "agent_confidence": {"type": "float"},
                        "human_verdict":    {"type": "keyword"},
                        "human_feedback":   {"type": "text"},
                        "typology_matched": {"type": "keyword"},
                        "decision_id":      {"type": "keyword"},
                        "timestamp":        {"type": "date"},
                        "sar_generated":    {"type": "boolean"},
                        "sar_pdf_url":      {"type": "keyword"},
                        "learning_applied": {"type": "boolean"},
                    }
                }
            },
        )

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
        log.error(f"[history_builder] Failed to store verdict: {exc}")


def _bulk_index_transactions(user_id: str, txns: list[dict]):
    es = get_client()
    try:
        es.delete_by_query(
            index=INDEX_TRANSACTIONS,
            body={"query": {"term": {"user_id": user_id}}},
            refresh=True,
            conflicts="proceed",
        )
    except Exception as exc:
        log.warning(f"[history_builder] Delete existing txns failed: {exc}")

    if not txns:
        return

    operations = []
    for t in txns:
        operations.append({"index": {"_index": INDEX_TRANSACTIONS}})
        operations.append(t)
    es.bulk(body=operations, refresh=True)
    log.info(f"[history_builder] Indexed {len(txns)} transactions for {user_id}")


def _compute_baseline(user_id: str, txns: list[dict]) -> dict:
    amounts = sorted([t["amount"] for t in txns if t["amount"] > 0])
    if not amounts:
        return _empty_baseline(user_id)

    q1 = amounts[len(amounts) // 4]
    q3 = amounts[3 * len(amounts) // 4]
    iqr = q3 - q1
    upper_fence = q3 + 1.5 * iqr

    cleaned = [a for a in amounts if a <= upper_fence]
    mean_p   = statistics.mean(cleaned)  if cleaned          else 0.0
    median_p = statistics.median(cleaned) if cleaned         else 0.0
    std_p    = statistics.stdev(cleaned)  if len(cleaned)>=2 else 0.0

    known_vendors  = list({t["recipient_name"] for t in txns
                           if t.get("recipient_name") and t["recipient_name"] != "unknown"})
    known_accounts = list({t["account_number"] for t in txns if t.get("account_number")})

    rails = [t["payment_type"] for t in txns if t.get("payment_type")]
    preferred_rail = max(set(rails), key=rails.count) if rails else "ACH"

    return {
        "user_id":         user_id,
        "mean_payment":    round(mean_p, 2),
        "std_payment":     round(std_p, 2),
        "median_payment":  round(median_p, 2),
        "max_normal":      round(upper_fence, 2),
        "known_vendors":   known_vendors,
        "known_accounts": known_accounts,
        "preferred_rail":  preferred_rail,
        "transaction_count": len(txns),
        "built_at":        datetime.now(timezone.utc).isoformat(),
        "source":          "gmail",
    }


def _empty_baseline(user_id: str) -> dict:
    return {
        "user_id":         user_id,
        "mean_payment":    0.0,
        "std_payment":     0.0,
        "median_payment":  0.0,
        "max_normal":      10_000.0,
        "known_vendors":   [],
        "known_accounts":  [],
        "preferred_rail":  "ACH",
        "transaction_count": 0,
        "built_at":        datetime.now(timezone.utc).isoformat(),
        "source":          "empty",
    }


def _index_baseline(user_id: str, baseline: dict):
    es = get_client()
    try:
        es.delete_by_query(
            index=INDEX_BASELINES,
            body={"query": {"term": {"user_id": user_id}}},
            refresh=True,
            conflicts="proceed",
        )
    except Exception:
        pass
    es.index(index=INDEX_BASELINES, id=user_id, document=baseline, refresh=True)


def _seed_empty_baseline(user_id: str):
    _index_baseline(user_id, _empty_baseline(user_id))