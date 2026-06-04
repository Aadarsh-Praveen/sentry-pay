"""
agent/gmail_client.py
─────────────────────────────────────────────────────────────────────────────
Gmail API wrapper for SentryPay.

SIMPLIFIED: No keyword filter - fetches ALL inbox emails, Gemini decides
which are payment requests.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.auth import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GMAIL_SCOPES,
    get_user_tokens,
)

log = logging.getLogger("sentry-pay.gmail")

# Label name constants
LABEL_BLOCKED   = "SentryPay/BLOCKED"
LABEL_REVIEW    = "SentryPay/REVIEW"
LABEL_SAFE      = "SentryPay/SAFE"
LABEL_MONITORED = "SentryPay/Monitored"

# Gmail palette colours for each label
LABEL_COLOURS = {
    LABEL_BLOCKED:   {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"},
    LABEL_REVIEW:    {"backgroundColor": "#fad165", "textColor": "#594c05"},
    LABEL_SAFE:      {"backgroundColor": "#16a766", "textColor": "#ffffff"},
    LABEL_MONITORED: {"backgroundColor": "#c2c2c2", "textColor": "#000000"},
}


def _build_credentials(user_id: str) -> Credentials:
    tokens = get_user_tokens(user_id)
    if not tokens or not tokens.get("access_token"):
        raise PermissionError(f"No Gmail tokens stored for user {user_id}")
    creds = Credentials(
        token         = tokens["access_token"],
        refresh_token = tokens.get("refresh_token"),
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = GOOGLE_CLIENT_ID,
        client_secret = GOOGLE_CLIENT_SECRET,
        scopes        = GMAIL_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            log.info(f"[gmail] Refreshed token for user {user_id}")
        except Exception as exc:
            log.error(f"[gmail] Refresh failed: {exc}")
            raise PermissionError("Gmail token expired - re-auth needed")
    return creds


def _service(user_id: str):
    creds = _build_credentials(user_id)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def ensure_labels(user_id: str) -> dict:
    service = _service(user_id)
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    name_to_id = {lbl["name"]: lbl["id"] for lbl in existing}
    for label_name, colour in LABEL_COLOURS.items():
        if label_name in name_to_id:
            continue
        try:
            new_label = service.users().labels().create(
                userId="me",
                body={
                    "name":                  label_name,
                    "labelListVisibility":   "labelShow",
                    "messageListVisibility": "show",
                    "color":                 colour,
                },
            ).execute()
            name_to_id[label_name] = new_label["id"]
            log.info(f"[gmail] Created label: {label_name}")
        except HttpError as exc:
            log.warning(f"[gmail] Could not create label {label_name}: {exc}")
    return name_to_id


def apply_label(user_id: str, message_id: str, verdict: str):
    label_map = ensure_labels(user_id)
    name_for_verdict = {
        "BLOCK":    LABEL_BLOCKED,
        "FRICTION": LABEL_REVIEW,
        "ALLOW":    LABEL_SAFE,
    }
    label_name = name_for_verdict.get(verdict)
    if not label_name:
        return
    label_ids = [label_map[label_name], label_map[LABEL_MONITORED]]
    try:
        _service(user_id).users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": label_ids},
        ).execute()
    except HttpError as exc:
        log.error(f"[gmail] Failed to apply label: {exc}")


def list_messages(
    user_id:     str,
    after_date:  Optional[datetime] = None,
    max_results: int = 200,
) -> list[dict]:
    """List all INBOX messages since the given date. NO keyword filter."""
    service = _service(user_id)

    query_parts = ["in:inbox"]
    if after_date:
        query_parts.append(f"after:{int(after_date.timestamp())}")
    query = " ".join(query_parts)

    log.info(f"[gmail] Query: {query!r}")

    msgs = []
    page_token = None

    while True:
        req = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(100, max_results - len(msgs)),
            pageToken=page_token,
        )
        resp = req.execute()
        page = resp.get("messages", []) or []
        msgs.extend(page)
        log.info(f"[gmail] Page returned {len(page)} messages - running total {len(msgs)}")

        page_token = resp.get("nextPageToken")
        if not page_token or len(msgs) >= max_results:
            break

    return msgs[:max_results]


def get_message(user_id: str, message_id: str) -> dict:
    service = _service(user_id)
    raw = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()

    headers = {h["name"].lower(): h["value"] for h in raw["payload"].get("headers", [])}
    body = _extract_body(raw["payload"])
    sender_raw = headers.get("from", "")
    sender_email = _extract_email_address(sender_raw)

    try:
        date = parsedate_to_datetime(headers.get("date", "")).isoformat()
    except Exception:
        date = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=timezone.utc).isoformat()

    return {
        "id":           raw["id"],
        "thread_id":    raw["threadId"],
        "subject":      headers.get("subject", "(no subject)"),
        "sender":       sender_raw,
        "sender_email": sender_email,
        "date":         date,
        "body":         body,
        "snippet":      raw.get("snippet", ""),
        "labels":       raw.get("labelIds", []),
    }


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return _decode_base64(payload["body"]["data"])
    parts = payload.get("parts", [])
    text_plain = ""
    text_html  = ""
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            text_plain = _decode_base64(part["body"]["data"])
        elif mime == "text/html" and part.get("body", {}).get("data"):
            text_html = _decode_base64(part["body"]["data"])
        elif mime.startswith("multipart/"):
            nested = _extract_body(part)
            if nested:
                return nested
    if text_plain:
        return text_plain
    if text_html:
        return _html_to_text(text_html)
    return ""


def _decode_base64(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _html_to_text(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_email_address(from_header: str) -> str:
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1)
    return from_header.strip()


def fetch_emails_since(user_id: str, since: datetime, max_results: int = 200) -> list[dict]:
    """Fetch ALL inbox emails since the given datetime."""
    msgs = list_messages(user_id=user_id, after_date=since, max_results=max_results)
    log.info(f"[gmail] User {user_id}: found {len(msgs)} messages in inbox since {since.isoformat()}")
    return [get_message(user_id, m["id"]) for m in msgs]


def fetch_emails_for_history(user_id: str, days: int = 90) -> list[dict]:
    """Fetch ALL inbox emails from the last N days for baseline building."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return fetch_emails_since(user_id, since, max_results=200)