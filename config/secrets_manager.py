"""
SentryPay — Secret Manager
============================
Centralises all secret/credential access for the project.

Priority order for each secret:
  1. GCP Secret Manager   — used in production (Cloud Run)
  2. Environment variable — used in local development (.env file)

Why Secret Manager:
    Storing API keys in .env files is acceptable for local development
    but creates risk in production — .env files can be accidentally
    committed, leaked in logs, or exposed via environment variable
    inspection. GCP Secret Manager stores secrets encrypted at rest,
    provides audit logs of every access, and allows secret rotation
    without redeploying the application.

Secrets managed:
    ELASTIC_API_KEY       — Elasticsearch authentication
    ELASTIC_ENDPOINT      — Elasticsearch cluster URL
    GCP_PROJECT_ID        — Google Cloud project identifier
    SENTRY_PAY_API_KEY    — SentryPay REST API authentication key
    BIGQUERY_DATASET      — BigQuery dataset name

Usage:
    from config.secrets_manager import get_secret
    api_key = get_secret("ELASTIC_API_KEY")

Setup (run once to store secrets in Secret Manager):
    python config/secrets_manager.py --setup
"""

import os
import sys
from dotenv import load_dotenv
from colorama import Fore, init

load_dotenv()
init(autoreset=True)

GCP_PROJECT = os.getenv("GCP_PROJECT_ID")

# Secrets to manage — maps secret name to env variable fallback
SECRETS = {
    "ELASTIC_API_KEY":    os.getenv("ELASTIC_API_KEY"),
    "ELASTIC_ENDPOINT":   os.getenv("ELASTIC_ENDPOINT"),
    "SENTRY_PAY_API_KEY": os.getenv("SENTRY_PAY_API_KEY", "sentry-pay-dev-key-2026"),
    "BIGQUERY_DATASET":   os.getenv("BIGQUERY_DATASET", "sentry_pay"),
}

# Cache loaded secrets in memory to avoid repeated API calls
_secret_cache: dict[str, str] = {}


def get_secret(name: str, use_cache: bool = True) -> str:
    """
    Retrieve a secret by name.

    Tries GCP Secret Manager first. Falls back to environment variable
    if Secret Manager is unavailable or the secret does not exist there.
    Caches the result in memory for the lifetime of the process.

    Args:
        name (str): the secret name (e.g. "ELASTIC_API_KEY")
        use_cache (bool): if True, return cached value if available

    Returns:
        str: the secret value

    Raises:
        ValueError: if the secret cannot be found in either source
    """
    if use_cache and name in _secret_cache:
        return _secret_cache[name]

    # Try GCP Secret Manager first
    value = _from_secret_manager(name)

    # Fall back to environment variable
    if not value:
        value = os.getenv(name) or SECRETS.get(name)

    if not value:
        raise ValueError(
            f"Secret '{name}' not found in Secret Manager or environment. "
            f"Add it to .env or run: python config/secrets_manager.py --setup"
        )

    _secret_cache[name] = value
    return value


def _from_secret_manager(name: str) -> str | None:
    """
    Attempt to retrieve a secret from GCP Secret Manager.

    Returns None silently if:
      - The google-cloud-secret-manager package is not installed
      - The GCP_PROJECT_ID is not set
      - The secret does not exist in Secret Manager
      - Insufficient IAM permissions

    Args:
        name (str): Secret Manager secret ID

    Returns:
        str | None: secret value or None if unavailable
    """
    if not GCP_PROJECT:
        return None

    try:
        from google.cloud import secretmanager

        client  = secretmanager.SecretManagerServiceClient()
        path    = f"projects/{GCP_PROJECT}/secrets/{name}/versions/latest"
        response = client.access_secret_version(request={"name": path})
        return response.payload.data.decode("UTF-8").strip()

    except Exception:
        # Any failure — fall through to env variable
        return None


def store_secret(name: str, value: str):
    """
    Store or update a secret in GCP Secret Manager.

    Creates the secret if it does not exist, then adds a new version
    with the provided value. Previous versions are kept but the latest
    version is the one returned by get_secret().

    Args:
        name (str): secret ID to create or update
        value (str): the secret value to store

    Raises:
        RuntimeError: if Secret Manager is not accessible
    """
    if not GCP_PROJECT:
        raise RuntimeError("GCP_PROJECT_ID must be set to use Secret Manager")

    try:
        from google.cloud import secretmanager
        from google.api_core.exceptions import AlreadyExists

        client     = secretmanager.SecretManagerServiceClient()
        parent     = f"projects/{GCP_PROJECT}"
        secret_id  = name

        # Create secret if it doesn't exist
        try:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}}
                }
            )
            print(Fore.GREEN + f"Created secret: {name}")
        except AlreadyExists:
            print(Fore.YELLOW + f"Secret exists, adding new version: {name}")

        # Add the secret value as a new version
        secret_path = f"{parent}/secrets/{secret_id}"
        client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": value.encode("UTF-8")}
            }
        )
        print(Fore.GREEN + f"Secret stored: {name}")

    except Exception as e:
        raise RuntimeError(f"Failed to store secret '{name}': {e}")


def setup_all_secrets():
    """
    Upload all secrets from the local .env file to GCP Secret Manager.

    Run this once after setting up a new GCP project to migrate
    from local .env to Secret Manager. Reads values from environment
    variables and stores them securely in Secret Manager.

    Usage:
        python config/secrets_manager.py --setup
    """
    print(Fore.CYAN + "\n SentryPay: Secret Manager Setup \n")
    print(f"  Project: {GCP_PROJECT}\n")

    secrets_to_upload = {
        "ELASTIC_API_KEY":  os.getenv("ELASTIC_API_KEY"),
        "ELASTIC_ENDPOINT": os.getenv("ELASTIC_ENDPOINT"),
        "SENTRY_PAY_API_KEY": os.getenv("SENTRY_PAY_API_KEY", "sentry-pay-dev-key-2026"),
    }

    for name, value in secrets_to_upload.items():
        if not value:
            print(Fore.YELLOW + f"Skipping {name} — not set in .env")
            continue
        try:
            store_secret(name, value)
        except Exception as e:
            print(Fore.RED + f"Failed {name}: {e}")

    print(Fore.CYAN + "\n Setup complete. \n")


def verify_all_secrets():
    """
    Verify all required secrets are accessible.

    Attempts to retrieve each required secret and reports which
    are available from Secret Manager vs environment variables.

    Usage:
        python config/secrets_manager.py --verify
    """
    print(Fore.CYAN + "\n Secret Verification \n")

    required = ["ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "SENTRY_PAY_API_KEY"]

    for name in required:
        sm_value  = _from_secret_manager(name)
        env_value = os.getenv(name)

        if sm_value:
            print(f"  {Fore.GREEN}✓{Fore.RESET}  {name}: Secret Manager")
        elif env_value:
            print(f"  {Fore.YELLOW}⚠{Fore.RESET}  {name}: env variable only (use --setup for production)")
        else:
            print(f"  {Fore.RED}✗{Fore.RESET}  {name}: NOT FOUND")

    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup",  action="store_true", help="Upload .env secrets to Secret Manager")
    parser.add_argument("--verify", action="store_true", help="Verify all secrets are accessible")
    args = parser.parse_args()

    if args.setup:
        setup_all_secrets()
    elif args.verify:
        verify_all_secrets()
    else:
        print("Usage: python config/secrets_manager.py --setup | --verify")