#!/usr/bin/env python3
"""
setup/seed_gmail_demo.py
─────────────────────────────────────────────────────────────────────────────
Seeds the SentryPay demo Gmail account with 50 realistic emails to
demonstrate the fraud detection capabilities end-to-end.

What it does:
  1. Reads Gmail OAuth tokens from BigQuery (users table)
  2. Generates 50 realistic emails spread across the last 90 days
  3. Inserts them into the user's Gmail inbox using messages.insert
     (with internalDateSource=dateHeader for proper backdating)

Mix of emails:
  - 35 regular invoices from recurring vendors (legit baseline)
  - 8 payment confirmations
  - 4 marketing emails (will be filtered out by extractor)
  - 3 BEC scam attempts (should be flagged when the monitor runs)

Run: python -m setup.seed_gmail_demo <email_address>
  e.g. python -m setup.seed_gmail_demo sentrypaydemo@gmail.com
"""

from __future__ import annotations

import base64
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

# Project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
# 50-EMAIL CORPUS — realistic small-business accounts payable mailbox
# ════════════════════════════════════════════════════════════════════════════
def _build_emails(recipient: str) -> list[dict]:
    """
    Build 50 emails spread across the last 90 days.

    Each dict has: {sender_email, sender_name, subject, body, days_ago}
    """
    emails = []

    # ── RECURRING VENDORS (legit) ──────────────────────────────────────────
    # 1. City Office Supplies — monthly invoices ~$800-900
    for i, days in enumerate([4, 35, 65, 88]):
        amount = round(random.uniform(820, 920), 2)
        inv    = 7042 + i
        emails.append({
            "sender_email": "jenny@cityofficesupplies.com",
            "sender_name":  "Jenny Parker",
            "subject":      f"Invoice #{inv} — Office Supplies",
            "body": f"""Hi Sarah,

Please find attached invoice #{inv} for office supplies — ${amount}.

Same bank account as always, no changes:
  Account: GB82WEST12345698765432
  Payment type: ACH

Thanks for your continued business.

Kind regards,
Jenny Parker
City Office Supplies""",
            "days_ago": days,
        })

    # 2. Hallmark Payroll — monthly payroll ~$27,500-28,500
    for i, days in enumerate([2, 32, 62]):
        amount = round(random.uniform(27_400, 28_600), 2)
        emails.append({
            "sender_email": "payroll@hallmark.com",
            "sender_name":  "Hallmark Payroll Services",
            "subject":      f"Monthly Payroll Reminder — ${amount:,.2f}",
            "body": f"""Hi Sarah,

Monthly payroll reminder.

Please process this month's payroll of ${amount:,.2f} to Hallmark Payroll
Services as usual. No changes to account details.

  Account: GB76LOYD30114900000000
  Payment type: ACH
  Reference: PAYROLL-{datetime.now().strftime('%Y%m')}

Regards,
Hallmark Payroll Services""",
            "days_ago": days,
        })

    # 3. BuildRight Materials — site supplies $5,000-8,000
    for i, days in enumerate([6, 22, 48, 71]):
        amount = round(random.uniform(5_500, 7_800), 2)
        inv    = 5510 + i
        emails.append({
            "sender_email": "accounts@buildright-materials.co.uk",
            "sender_name":  "BuildRight Materials",
            "subject":      f"Invoice #{inv} — Materials Delivery",
            "body": f"""Hi Sarah,

BuildRight invoice #{inv} for materials delivered to the Farringdon site.

  Amount:  ${amount:,.2f}
  Account: GB33BUKB20201555555555
  Payment type: ACH

Same bank details as always.

Thank you,
BuildRight Materials""",
            "days_ago": days,
        })

    # 4. MetroCity Insurance — quarterly premium ~$4,000-4,500
    for i, days in enumerate([15, 75]):
        amount = round(random.uniform(4_100, 4_400), 2)
        emails.append({
            "sender_email": "billing@metrocityinsurance.com",
            "sender_name":  "MetroCity Insurance",
            "subject":      "Quarterly Insurance Premium",
            "body": f"""Hi Sarah,

MetroCity Insurance — quarterly premium invoice.

  Amount due:   ${amount:,.2f}
  Due date:     {(datetime.now() - timedelta(days=days-10)).strftime('%d %b %Y')}
  Account:      GB06NWBK60161331926820
  Payment type: ACH

No changes to our payment details. Please process at your earliest convenience.

MetroCity Insurance Group""",
            "days_ago": days,
        })

    # 5. Apex Scaffolding — site work invoices $7,000-10,000
    for i, days in enumerate([8, 27, 54, 82]):
        amount = round(random.uniform(7_200, 9_800), 2)
        inv    = 1840 + i
        emails.append({
            "sender_email": "mike@apex-scaffolding.co.uk",
            "sender_name":  "Mike Johnson",
            "subject":      f"Scaffolding Invoice #{inv} — Site Work",
            "body": f"""Hi Sarah,

Apex Scaffolding — Invoice #{inv} for site work this month.

  Amount:       ${amount:,.2f}
  Account:      GB29NWBK60161331926819
  Payment type: Wire
  Reference:    APEX-{inv}

Same account as always — no changes.

Thanks,
Mike Johnson
Apex Scaffolding Ltd""",
            "days_ago": days,
        })

    # 6. Freightline Logistics — monthly freight $7,500-9,000
    for i, days in enumerate([10, 41, 79]):
        amount = round(random.uniform(7_600, 8_900), 2)
        inv    = 9018 + i
        emails.append({
            "sender_email": "billing@freightline-logistics.com",
            "sender_name":  "Freightline Logistics",
            "subject":      f"Monthly Freight Invoice #{inv}",
            "body": f"""Hi,

Freightline Logistics — Invoice #{inv}.

  Freight charges this month: ${amount:,.2f}
  Account:      US09876543210987654321
  Payment type: Wire

Payment to our standard account as usual.

Freightline Logistics""",
            "days_ago": days,
        })

    # 7. TechPro IT Services — monthly IT support $3,300-3,700
    for i, days in enumerate([12, 43, 73]):
        amount = round(random.uniform(3_400, 3_650), 2)
        emails.append({
            "sender_email": "accounts@techpro-services.com",
            "sender_name":  "TechPro IT Services",
            "subject":      "Monthly IT Support Invoice",
            "body": f"""Hi Sarah,

Monthly IT support invoice — ${amount:,.2f}.

  Account:      GB55TECH00000012345678
  Payment type: ACH

Same details as always.

TechPro IT Services""",
            "days_ago": days,
        })

    # 8. CleanPro Janitorial — weekly cleaning $1,700-1,900
    for i, days in enumerate([14, 44, 74]):
        amount = round(random.uniform(1_750, 1_880), 2)
        emails.append({
            "sender_email": "invoices@cleanpro-janitorial.com",
            "sender_name":  "CleanPro Janitorial",
            "subject":      "Monthly Cleaning Services",
            "body": f"""Hi Sarah,

CleanPro Janitorial — monthly invoice for cleaning services.

  Amount: ${amount:,.2f}
  Account:      US34343434343434343434
  Payment type: ACH

Please process to our usual account.

CleanPro Janitorial""",
            "days_ago": days,
        })

    # 9. BuildRight Advisory — consulting $8,000-10,000
    for i, days in enumerate([18, 60]):
        amount = round(random.uniform(8_200, 9_900), 2)
        inv    = 8820 + i
        emails.append({
            "sender_email": "derek@buildright-advisory.com",
            "sender_name":  "Derek Walsh",
            "subject":      f"Invoice #{inv} — Consulting Services",
            "body": f"""Hi Sarah,

Please find attached invoice #{inv} for consulting services this month — ${amount:,.2f} net 30.

  Account:      US44FIRST00000112233445
  Payment type: ACH

Kind regards,
Derek Walsh
BuildRight Advisory Services""",
            "days_ago": days,
        })

    # 10. Westfield Utilities — utility bills $850-1,100
    for i, days in enumerate([20, 50, 80]):
        amount = round(random.uniform(870, 1_080), 2)
        emails.append({
            "sender_email": "billing@westfield-utilities.com",
            "sender_name":  "Westfield Utilities",
            "subject":      f"Utility Invoice — ${amount:,.2f}",
            "body": f"""Dear Customer,

Your utility invoice for the period is ready.

  Amount due:   ${amount:,.2f}
  Account:      GB99WEST00000044556677
  Payment type: Direct Debit

Westfield Utilities""",
            "days_ago": days,
        })

    # ── PAYMENT CONFIRMATIONS (no payment request) ─────────────────────────
    confirmation_pairs = [
        ("City Office Supplies",      "GB82WEST12345698765432", 847.50,  3),
        ("Hallmark Payroll Services", "GB76LOYD30114900000000", 27_800,  1),
        ("Apex Scaffolding Ltd",      "GB29NWBK60161331926819", 8_500,   7),
        ("BuildRight Materials",      "GB33BUKB20201555555555", 6_200,   23),
        ("MetroCity Insurance",       "GB06NWBK60161331926820", 4_180,   16),
        ("Freightline Logistics",     "US09876543210987654321", 8_200,   11),
        ("TechPro IT Services",       "GB55TECH00000012345678", 3_500,   13),
        ("BuildRight Advisory",       "US44FIRST00000112233445", 9_500,   19),
    ]
    for vendor, account, amount, days in confirmation_pairs:
        emails.append({
            "sender_email": "no-reply@bank-notifications.com",
            "sender_name":  "Bank Notifications",
            "subject":      f"Payment Confirmation — ${amount:,.2f} to {vendor}",
            "body": f"""This is to confirm your payment.

  Amount:    ${amount:,.2f}
  To:        {vendor}
  Account:   {account}
  Reference: PAYMENT-{vendor[:4].upper()}-2026
  Date:      {(datetime.now() - timedelta(days=days)).strftime('%d %b %Y')}

Your payment has been processed successfully.

This is an automated confirmation. Do not reply.""",
            "days_ago": days,
        })

    # ── MARKETING / NON-PAYMENT (will be filtered out) ─────────────────────
    emails.append({
        "sender_email": "newsletter@cloudaccounting.com",
        "sender_name":  "CloudAccounting Newsletter",
        "subject":      "5 ways to optimise your AP workflow",
        "body":         "This month's newsletter covers automation tips for accounts payable teams...",
        "days_ago":     9,
    })
    emails.append({
        "sender_email": "events@cfo-summit.com",
        "sender_name":  "CFO Summit",
        "subject":      "You're invited: CFO Summit 2026",
        "body":         "Join us at the CFO Summit 2026 in London. Register today...",
        "days_ago":     31,
    })
    emails.append({
        "sender_email": "team@spotify.com",
        "sender_name":  "Spotify Business",
        "subject":      "Your monthly playlist update",
        "body":         "New podcasts and music for your team this month...",
        "days_ago":     55,
    })
    emails.append({
        "sender_email": "marketing@linkedin.com",
        "sender_name":  "LinkedIn",
        "subject":      "5 new connections want to connect with you",
        "body":         "See who's interested in connecting on LinkedIn...",
        "days_ago":     67,
    })

    # ── SCAM ATTEMPTS (should trigger BLOCK when monitor analyses them) ────
    # 1. Look-alike domain BEC — Apex Scaffolding impersonation
    emails.append({
        "sender_email": "mike@apex-scaff0lding.com",  # zero instead of 'o'
        "sender_name":  "Mike Johnson",
        "subject":      "URGENT: Updated Banking Details — Apex Scaffolding",
        "body": """Hi Sarah,

Hope you're well. Just a quick note — we've recently migrated our treasury
operations to a new banking provider due to consolidation. Could you please
update your records and ensure the upcoming invoice of $47,000 is sent to
our new account?

New account details:
  Bank:    Metro Bank UK
  Account: GB94METRO00000087654321
  Sort:    00-00-87

Please treat this as urgent as the invoice is due this Friday.
Do NOT call our old number — we are migrating phone systems too.

Best regards,
Mike Johnson
Apex Scaffolding Ltd""",
        "days_ago": 1,  # very recent
    })

    # 2. CEO impersonation (gift cards / urgent wire)
    emails.append({
        "sender_email": "ceo@company-board.com",
        "sender_name":  "James Holden",
        "subject":      "Urgent — Confidential Wire Transfer Required",
        "body": """Sarah,

I need a wire transfer processed today before 4pm for $32,500 to close
an acquisition deal. This is highly confidential — please do not discuss
with anyone else on the team or with our usual finance contacts.

Send to:
  Beneficiary: Apex Acquisitions LLC
  Account:     US11SHELL00000099887766
  Routing:     021000089

I'll explain everything in our 1:1 tomorrow. Just get this sent today.

Thanks,
James
CEO""",
        "days_ago": 5,
    })

    # 3. Fake invoice from new vendor with urgent pressure
    emails.append({
        "sender_email": "billing@quickpay-services.io",
        "sender_name":  "QuickPay Services",
        "subject":      "OVERDUE Invoice #INV-9921 — Action Required",
        "body": """Dear Accounts Payable,

This is the second notice for OVERDUE invoice #INV-9921 in the amount
of $18,750 for consulting services provided in March.

Please remit payment within 48 hours to avoid late fees and credit
reporting action.

  Beneficiary: QuickPay Services
  Account:     US77FAST00000054433221
  Payment type: Wire

If not received by EOD Friday, we will escalate to collections.

QuickPay Services Billing Dept""",
        "days_ago": 2,
    })

    # Sort by days_ago descending so oldest emails are processed first
    emails.sort(key=lambda e: -e["days_ago"])
    return emails


# ════════════════════════════════════════════════════════════════════════════
# Gmail API helpers
# ════════════════════════════════════════════════════════════════════════════
def _get_credentials_for_email(email: str) -> Credentials:
    """Look up the user in BigQuery and build Gmail credentials."""
    bq = bigquery.Client(project=GCP_PROJECT)
    query = f"""
        SELECT gmail_access_token, gmail_refresh_token, email
        FROM `{USERS_TABLE}`
        WHERE email = @email LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", email)]
    )
    rows = list(bq.query(query, job_config=job_config).result())
    if not rows:
        raise SystemExit(
            f"\n  No user found with email '{email}' in BigQuery.\n"
            f"   Sign in once via http://localhost:5173 with that account first.\n"
        )
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


def _insert_email(service, recipient: str, email: dict):
    """Insert one email into the user's Gmail inbox with a backdated timestamp."""
    timestamp = datetime.now(timezone.utc) - timedelta(
        days  = email["days_ago"],
        hours = random.randint(8, 17),
        minutes = random.randint(0, 59),
    )
    date_header = timestamp.strftime("%a, %d %b %Y %H:%M:%S %z")

    msg = MIMEText(email["body"])
    msg["To"]      = recipient
    msg["From"]    = f'{email["sender_name"]} <{email["sender_email"]}>'
    msg["Subject"] = email["subject"]
    msg["Date"]    = date_header

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    # Insert with internalDateSource=dateHeader so Gmail uses our Date header
    return service.users().messages().insert(
        userId = "me",
        body   = {
            "raw":      raw,
            "labelIds": ["INBOX"],
        },
        internalDateSource = "dateHeader",
    ).execute()


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════
def main():
    if len(sys.argv) < 2:
        recipient = "sentrypaydemo@gmail.com"
        print(f"  No email provided — defaulting to {recipient}")
    else:
        recipient = sys.argv[1]

    print(f"\n  Seeding demo emails for {recipient}")
    print(f"  Source: BigQuery {USERS_TABLE}\n")

    # Build credentials
    try:
        creds = _get_credentials_for_email(recipient)
    except SystemExit as exc:
        print(str(exc))
        sys.exit(1)

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    emails = _build_emails(recipient)

    print(f"  Inserting {len(emails)} emails (oldest first)...\n")
    success = 0
    failed  = 0
    for i, email in enumerate(emails, 1):
        try:
            _insert_email(service, recipient, email)
            ts_str = (datetime.now() - timedelta(days=email["days_ago"])).strftime("%Y-%m-%d")
            print(f"  [{i:2}/{len(emails)}] {ts_str}  →  {email['subject'][:60]}")
            success += 1
            # Gentle rate limit — Gmail API allows ~250 quota units/sec
            time.sleep(0.15)
        except HttpError as exc:
            print(f"  [{i:2}/{len(emails)}] FAILED: {email['subject'][:60]} — {exc}")
            failed += 1
        except Exception as exc:
            print(f"  [{i:2}/{len(emails)}] FAILED: {email['subject'][:60]} — {exc}")
            failed += 1

    print(f"\n  Done. {success} inserted, {failed} failed.")
   


if __name__ == "__main__":
    main()