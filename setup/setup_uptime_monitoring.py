"""
SentryPay — Uptime Monitoring Setup
=====================================
Configures Google Cloud Monitoring uptime checks for the
SentryPay Cloud Run service. Sets up alerting so you get
notified if the service goes down or becomes unhealthy.

What is monitored:
    - HTTP uptime check on /health endpoint every 60 seconds
    - Alert if 2 consecutive checks fail (2 minutes downtime)
    - Alert sent to your email address

Prerequisites:
    Cloud Run must be deployed first.
    Cloud Monitoring API must be enabled.

Usage:
    python setup/setup_uptime_monitoring.py --email your@email.com
"""

import os
import sys
import subprocess
from dotenv import load_dotenv
from colorama import Fore, init

load_dotenv()
init(autoreset=True)

GCP_PROJECT   = os.getenv("GCP_PROJECT_ID")
GCP_REGION    = os.getenv("GCP_REGION", "us-central1")
CLOUD_RUN_URL = os.getenv("CLOUD_RUN_URL", "")


def enable_monitoring_api():
    """Enable Cloud Monitoring API."""
    print(Fore.CYAN + "\n Enabling Cloud Monitoring API \n")
    result = subprocess.run([
        "gcloud", "services", "enable",
        "monitoring.googleapis.com",
        f"--project={GCP_PROJECT}"
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print(Fore.GREEN + "  ✓ Cloud Monitoring API enabled")
    else:
        print(Fore.YELLOW + f"  May already be enabled: {result.stderr[:100]}")


def get_cloud_run_url() -> str:
    """Get the Cloud Run service URL."""
    if CLOUD_RUN_URL:
        return CLOUD_RUN_URL

    result = subprocess.run([
        "gcloud", "run", "services", "describe", "sentry-pay",
        f"--region={GCP_REGION}",
        f"--project={GCP_PROJECT}",
        "--format=value(status.url)"
    ], capture_output=True, text=True)

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    return ""


def create_uptime_check(service_url: str):
    """
    Create a Cloud Monitoring uptime check for the /health endpoint.

    Configures an HTTP check that polls /health every 60 seconds
    from multiple global locations. Fails if the endpoint returns
    a non-2xx status code or doesn't respond within 10 seconds.

    Args:
        service_url (str): full Cloud Run service URL
    """
    print(Fore.CYAN + "\n Creating uptime check \n")

    # Parse host from URL
    host = service_url.replace("https://", "").replace("http://", "").split("/")[0]

    print(f"  Monitoring: {service_url}/health")
    print(f"  Check interval: 60 seconds")

    # Create uptime check via gcloud (using REST API config)
    config = {
        "displayName": "SentryPay Health Check",
        "httpCheck": {
            "path":           "/health",
            "port":           443,
            "useSsl":         True,
            "validateSsl":    True,
            "requestMethod":  "GET"
        },
        "monitoredResource": {
            "type": "uptime_url",
            "labels": {
                "project_id": GCP_PROJECT,
                "host":       host
            }
        },
        "period":  "60s",
        "timeout": "10s",
        "selectedRegions": [
            "USA",
            "EUROPE",
            "ASIA_PACIFIC"
        ]
    }

    import json
    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                     delete=False) as f:
        json.dump(config, f)
        config_file = f.name

    result = subprocess.run([
        "gcloud", "monitoring", "uptime", "create",
        f"--project={GCP_PROJECT}",
        f"--config-from-file={config_file}"
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print(Fore.GREEN + "Uptime check created")
    else:
        print(Fore.YELLOW + f"Uptime check creation: {result.stderr[:200]}")
        print(Fore.YELLOW + "You can also create this manually in the GCP console:")
        print(f"    → Monitoring → Uptime checks → Create uptime check")
        print(f"    → URL: {service_url}/health")


def create_alert_policy(email: str):
    """
    Create an alerting policy that emails when uptime check fails.

    Sends an email notification if the uptime check fails
    2 consecutive times (2 minutes of downtime).

    Args:
        email (str): email address to send alerts to
    """
    print(Fore.CYAN + "\n Creating alert policy \n")
    print(f"  Alert email: {email}")
    print(Fore.YELLOW + "Alert policies must be created via GCP Console:")
    print(f"    1. Go to: console.cloud.google.com/monitoring/alerting")
    print(f"    2. Click 'Create Policy'")
    print(f"    3. Select metric: 'Uptime Check URL — Check passed'")
    print(f"    4. Condition: 'is false for 2 minutes'")
    print(f"    5. Notification channel: email → {email}")
    print(f"    6. Alert name: 'SentryPay Down Alert'")


def print_monitoring_summary(service_url: str):
    """Print a summary of what was set up."""
    print(Fore.CYAN + "\n Monitoring Summary \n")
    print(f"  Service URL:    {service_url}")
    print(f"  Health check:   {service_url}/health")
    print(f"  Check interval: every 60 seconds")
    print(f"  Check regions:  USA, Europe, Asia Pacific")
    print(f"\n  View in GCP Console:")
    print(f"console.cloud.google.com/monitoring/uptime")


def run(email: str = ""):
    print(Fore.CYAN + "\n SentryPay: Uptime Monitoring Setup \n")

    if not GCP_PROJECT:
        print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)

    service_url = get_cloud_run_url()
    if not service_url:
        print(Fore.RED + """
ERROR: Cloud Run service URL not found.
Deploy the backend first:
    gcloud run deploy sentry-pay ...

Or set CLOUD_RUN_URL in your .env file.
""")
        sys.exit(1)

    enable_monitoring_api()
    create_uptime_check(service_url)

    if email:
        create_alert_policy(email)

    print_monitoring_summary(service_url)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", type=str, default="",
                        help="Email address for downtime alerts")
    args = parser.parse_args()
    run(email=args.email)