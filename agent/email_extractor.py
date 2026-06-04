"""
agent/email_extractor.py
─────────────────────────────────────────────────────────────────────────────
Use Gemini to extract structured payment details from raw email text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

from google import genai
from google.genai import types

log = logging.getLogger("sentry-pay.extractor")

GCP_PROJECT  = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_REGION", "us-central1")
GEMINI_MODEL = "gemini-2.5-flash"

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
    return _client


# Vertex AI schema (UPPERCASE types, nullable: True)
PAYMENT_DETAILS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "contains_payment_request": {"type": "BOOLEAN"},
        "is_confirmation":          {"type": "BOOLEAN"},
        "amount":                   {"type": "NUMBER", "nullable": True},
        "currency":                 {"type": "STRING", "nullable": True},
        "recipient_name":           {"type": "STRING", "nullable": True},
        "account_number":           {"type": "STRING", "nullable": True},
        "payment_type":             {"type": "STRING", "nullable": True},
        "urgency":                  {"type": "STRING", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "sender_domain":            {"type": "STRING", "nullable": True},
        "due_date":                 {"type": "STRING", "nullable": True},
        "summary":                  {"type": "STRING"},
    },
    "required": ["contains_payment_request", "is_confirmation", "urgency", "summary"],
}


# IMPROVED PROMPT — broader definition of "payment request"
EXTRACTION_PROMPT = """You extract payment details from business emails for fraud detection.

Return JSON with these fields:

contains_payment_request (bool): TRUE if the email is any of:
    - An invoice (recurring or one-off)
    - A bill or statement asking for payment
    - Banking/payment instructions
    - A request to wire, transfer, or send money
    - Anything from a vendor expecting to be paid
  FALSE only if the email is:
    - A confirmation of a payment ALREADY made (set is_confirmation=true instead)
    - Marketing / newsletters / event invitations
    - Internal team communication with no payment ask
    - Personal email with no money involved

is_confirmation (bool): TRUE if this confirms a payment that has ALREADY happened.
                        Examples: "Payment received", "Wire confirmed", "Receipt".

amount (number, nullable): the numeric amount (no currency symbol).
currency (string, nullable): "USD", "GBP", "EUR" etc.
recipient_name (string, nullable): the company or person to be paid.
account_number (string, nullable): IBAN, routing+account number etc.
payment_type (string, nullable): "Wire", "ACH", "Real-Time Payment", "Zelle", "Check".
urgency (string): "LOW" (no time pressure), "MEDIUM" (mentions due date),
                  "HIGH" (urgent/today/ASAP/Friday deadline/24 hours).
sender_domain (string, nullable): part after @ in sender email.
due_date (string, nullable): YYYY-MM-DD if a deadline is mentioned.
summary (string): one-sentence summary of the email.

IMPORTANT: Recurring monthly invoices ARE payment requests — set contains_payment_request=true.

EMAIL:
From:    {sender}
Subject: {subject}

{body}
"""


def _extract_sender_domain(sender: str) -> Optional[str]:
    m = re.search(r"@([\w\.\-]+)", sender)
    return m.group(1).lower() if m else None


def _sanitize_for_prompt(text: str, max_chars: int = 1500) -> str:
    if not text:
        return ""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "... [truncated]"
    return text


def _try_repair_json(text: str) -> Optional[dict]:
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        fixed = re.sub(r",(\s*[}\]])", r"\1", candidate)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    return None


def extract_payment_details(email: dict) -> dict:
    body = _sanitize_for_prompt(email.get("body") or "")

    prompt = EXTRACTION_PROMPT.format(
        sender  = email.get("sender", "")[:200],
        subject = (email.get("subject", "") or "")[:200],
        body    = body,
    )

    start = time.time()
    try:
        response = _get_client().models.generate_content(
            model    = GEMINI_MODEL,
            contents = prompt,
            config   = types.GenerateContentConfig(
                temperature       = 0.0,
                max_output_tokens = 800,
                response_mime_type= "application/json",
                response_schema   = PAYMENT_DETAILS_SCHEMA,
            ),
        )
        elapsed_ms = int((time.time() - start) * 1000)

        text    = (response.text or "").strip()
        details = _try_repair_json(text)

        if details is None:
            log.warning(f"[extractor] JSON repair failed, falling back. Raw text: {text[:300]}")
            return _fallback_response(email, "json_parse_failed")

        if not details.get("sender_domain"):
            details["sender_domain"] = _extract_sender_domain(email.get("sender", ""))

        details.setdefault("contains_payment_request", False)
        details.setdefault("is_confirmation",          False)
        details.setdefault("urgency",                  "LOW")
        details.setdefault("summary",                  "")

        log.info(f"[extractor] {elapsed_ms}ms — "
                 f"is_request={details.get('contains_payment_request')} "
                 f"amount={details.get('amount')} "
                 f"subject='{email.get('subject', '')[:40]}'")
        return details

    except Exception as exc:
        log.error(f"[extractor] Gemini call failed: {exc}")
        return _fallback_response(email, str(exc))


def _fallback_response(email: dict, error: str) -> dict:
    return {
        "contains_payment_request": False,
        "is_confirmation":          False,
        "amount":                   None,
        "currency":                 None,
        "recipient_name":           None,
        "account_number":           None,
        "payment_type":             None,
        "urgency":                  "LOW",
        "sender_domain":            _extract_sender_domain(email.get("sender", "")),
        "due_date":                 None,
        "summary":                  f"Extraction failed: {error[:100]}",
        "_extraction_error":        error,
    }