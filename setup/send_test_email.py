#!/usr/bin/env python3
"""
setup/send_test_email.py
─────────────────────────────────────────────────────────────────────────────
Sends ONE fresh test email to sentrypaydemo@gmail.com with today's
timestamp — so the email monitor will pick it up as a "new" email.

Run: python -m setup.send_test_email
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

GCP_PROJECT          = os.getenv("GCP_PROJECT_ID")
BQ_DATASET           = os.getenv("BIGQUERY_DATASET", "sentry_pay")
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

USERS_TABLE = f"{GCP_PROJECT}.{BQ_DATASET}.users"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
]


# ════════════════════════════════════════════════════════════════════════════
# A fresh BEC scam — impersonating BuildRight Materials (a vendor already in
# the user's baseline), redirecting payment to a new account.
# ════════════════════════════════════════════════════════════════════════════
TEST_EMAIL = {
    "sender_email": "accounts@buildright-supplies.com",  # look-alike domain
    "sender_name":  "BuildRight Materials",
    "subject":      "URGENT: BuildRight Banking Update - Action Required Today",
    "body": """Hi Sarah,

Hope you're well. Due to an unexpected issue with our previous bank, we've
had to switch banking providers urgently. Could you please send the
outstanding invoice payment of $34,500 to our new account today?

NEW ACCOUNT DETAILS (please update your records):
  Bank:    Tide Banking
  Account: GB99TIDE12399988877766
  Sort:    23-14-70

I know this is short notice, but the payment is overdue and we cannot wait
any longer due to cash flow issues. Please process this immediately and do
NOT call our old office number — phone lines are being migrated.

If you need to confirm, please email me back directly (do not call).

Thanks for understanding,
Derek Walsh
BuildRight Materials
""",
}


def _get_credentials_for_email(email: str) -> Credentials:
    bq = bigquery.Client(project=GCP_PROJECT)
    query = f"""
        SELECT gmail_access_token, gmail_refresh_token
        FROM `{USERS_TABLE}`
        WHERE email = @email LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", email)]
    )
    rows = list(bq.query(query, job_config=job_config).result())
    if not rows:
        raise SystemExit(f"  No user found with email '{email}'.")
    row = rows[0]
    creds = Credentials(
        token         = row.gmail_access_token,
        refresh_token = row.gmail_refresh_token,
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = GOOGLE_CLIENT_ID,
        client_secret = GOOGLE_CLIENT_SECRET,
        scopes        = GMAIL_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    return creds


def main():
    recipient = sys.argv[1] if len(sys.argv) > 1 else "sentrypaydemo@gmail.com"

    print(f"\n  Sending fresh test email to {recipient}\n")

    creds   = _get_credentials_for_email(recipient)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    # Build the message with CURRENT timestamp (so monitor sees it as new)
    now = datetime.now(timezone.utc)
    date_header = now.strftime("%a, %d %b %Y %H:%M:%S %z")

    msg = MIMEText(TEST_EMAIL["body"])
    msg["To"]      = recipient
    msg["From"]    = f'{TEST_EMAIL["sender_name"]} <{TEST_EMAIL["sender_email"]}>'
    msg["Subject"] = TEST_EMAIL["subject"]
    msg["Date"]    = date_header

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    result = service.users().messages().insert(
        userId = "me",
        body   = {
            "raw":      raw,
            "labelIds": ["INBOX", "UNREAD"],
        },
        internalDateSource = "dateHeader",
    ).execute()

    print(f"  Inserted message {result['id']}")
    print(f"  Subject:    {TEST_EMAIL['subject']}")
    print(f"  From:       {TEST_EMAIL['sender_email']}")
    print(f"  Timestamp:  {date_header}")



if __name__ == "__main__":
    main()