"""
SentryPay — Cloud Scheduler Deployment
=========================================
Deploys all automated data refresh and monitoring jobs
to Google Cloud Scheduler.

Jobs deployed:
    refresh-opensanctions     Daily 2 AM — refresh flagged accounts
    refresh-rss-feeds         Every 6 hours — new scam alerts
    run-drift-analysis        Weekly Sunday 4 AM — model drift check

Prerequisites:
    Cloud Run must be deployed before running this script.
    Cloud Scheduler API must be enabled.

Usage:
    python setup/deploy_cloud_scheduler.py
    python setup/deploy_cloud_scheduler.py --delete  # remove all jobs
"""

import os
import sys
import subprocess
from dotenv import load_dotenv
from colorama import Fore, init

load_dotenv()
init(autoreset=True)

GCP_PROJECT  = os.getenv("GCP_PROJECT_ID")
GCP_REGION   = os.getenv("GCP_REGION", "us-central1")
CLOUD_RUN_URL = os.getenv("CLOUD_RUN_URL", "")  # Set after Cloud Run deploy

# Scheduler jobs to create
JOBS = [
    {
        "name":        "sentry-pay-refresh-opensanctions",
        "schedule":    "0 2 * * *",          # Daily at 2 AM UTC
        "description": "Refresh OpenSanctions flagged accounts",
        "path":        "/refresh/opensanctions",
        "timezone":    "UTC"
    },
    {
        "name":        "sentry-pay-refresh-rss",
        "schedule":    "0 */6 * * *",        # Every 6 hours
        "description": "Monitor RSS feeds for new scam alerts",
        "path":        "/refresh/rss",
        "timezone":    "UTC"
    },
    {
        "name":        "sentry-pay-drift-analysis",
        "schedule":    "0 4 * * 0",          # Sundays at 4 AM UTC
        "description": "Run weekly drift analysis on agent decisions",
        "path":        "/analysis/drift",
        "timezone":    "UTC"
    }
]


def run_gcloud(args: list, check: bool = True) -> subprocess.CompletedProcess:
    """Run a gcloud command and return the result."""
    cmd = ["gcloud"] + args
    print(f"  Running: {' '.join(cmd[:6])}...")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def enable_scheduler_api():
    """Enable Cloud Scheduler API if not already enabled."""
    print(Fore.CYAN + "\n Enabling Cloud Scheduler API \n")
    result = run_gcloud([
        "services", "enable",
        "cloudscheduler.googleapis.com",
        f"--project={GCP_PROJECT}"
    ], check=False)

    if result.returncode == 0:
        print(Fore.GREEN + "Cloud Scheduler API enabled")
    else:
        print(Fore.YELLOW + f"May already be enabled: {result.stderr[:100]}")


def create_job(job: dict, cloud_run_url: str):
    """
    Create one Cloud Scheduler job.

    Creates an HTTP job that POSTs to the Cloud Run endpoint
    on the configured schedule. Uses OIDC authentication so
    Cloud Scheduler can call the authenticated Cloud Run service.

    Args:
        job (dict): job configuration
        cloud_run_url (str): base URL of the Cloud Run service
    """
    target_url = f"{cloud_run_url}{job['path']}"

    print(f"\n  Creating: {job['name']}")
    print(f"    Schedule: {job['schedule']} ({job['timezone']})")
    print(f"    Target:   {target_url}")

    # Delete existing job first (idempotent)
    run_gcloud([
        "scheduler", "jobs", "delete", job['name'],
        f"--location={GCP_REGION}",
        f"--project={GCP_PROJECT}",
        "--quiet"
    ], check=False)

    # Create new job
    result = run_gcloud([
        "scheduler", "jobs", "create", "http", job['name'],
        f"--location={GCP_REGION}",
        f"--project={GCP_PROJECT}",
        f"--schedule={job['schedule']}",
        f"--uri={target_url}",
        f"--time-zone={job['timezone']}",
        "--http-method=POST",
        "--message-body={}",
        "--headers=Content-Type=application/json",
        f"--description={job['description']}",
        "--attempt-deadline=600s",
        "--max-retry-attempts=2",
        "--min-backoff=30s"
    ], check=False)

    if result.returncode == 0:
        print(Fore.GREEN + f"  Created: {job['name']}")
    else:
        print(Fore.RED + f"  Failed: {result.stderr[:200]}")


def delete_all_jobs():
    """Delete all SentryPay scheduler jobs."""
    print(Fore.CYAN + "\n Deleting all scheduler jobs \n")
    for job in JOBS:
        result = run_gcloud([
            "scheduler", "jobs", "delete", job['name'],
            f"--location={GCP_REGION}",
            f"--project={GCP_PROJECT}",
            "--quiet"
        ], check=False)

        if result.returncode == 0:
            print(Fore.GREEN + f"  ✓ Deleted: {job['name']}")
        else:
            print(Fore.YELLOW + f"  ⚠ Not found: {job['name']}")


def list_jobs():
    """List all SentryPay scheduler jobs."""
    result = run_gcloud([
        "scheduler", "jobs", "list",
        f"--location={GCP_REGION}",
        f"--project={GCP_PROJECT}",
        "--format=table(name,schedule,state)"
    ], check=False)

    if result.stdout:
        print(Fore.CYAN + "\n Current scheduler jobs \n")
        print(result.stdout)


def run():
    print(Fore.CYAN + "\n SentryPay: Cloud Scheduler Setup \n")

    if not GCP_PROJECT:
        print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)

    cloud_run_url = CLOUD_RUN_URL
    if not cloud_run_url:
        # Try to get URL from gcloud
        result = run_gcloud([
            "run", "services", "describe", "sentry-pay",
            f"--region={GCP_REGION}",
            f"--project={GCP_PROJECT}",
            "--format=value(status.url)"
        ], check=False)

        if result.returncode == 0 and result.stdout.strip():
            cloud_run_url = result.stdout.strip()
            print(Fore.GREEN + f"  ✓ Cloud Run URL: {cloud_run_url}")
        else:
            print(Fore.RED + """
ERROR: Cloud Run URL not found.
Deploy the backend first:
    gcloud run deploy sentry-pay --image gcr.io/PROJECT_ID/sentry-pay

Or set CLOUD_RUN_URL in your .env file.
""")
            sys.exit(1)

    enable_scheduler_api()

    print(Fore.CYAN + "\n Creating scheduler jobs \n")
    for job in JOBS:
        create_job(job, cloud_run_url)

    list_jobs()

    print(Fore.CYAN + "\n Cloud Scheduler setup complete. \n")
    print(Fore.GREEN + "  Jobs will run automatically on their schedules.")
    print(Fore.YELLOW + "  To trigger a job manually:")
    print(f"  gcloud scheduler jobs run sentry-pay-refresh-opensanctions "
          f"--location={GCP_REGION}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true",
                        help="Delete all scheduler jobs")
    args = parser.parse_args()

    if args.delete:
        delete_all_jobs()
    else:
        run()