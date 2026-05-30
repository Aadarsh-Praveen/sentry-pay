"""
SentryPay — Elastic Client Factory
====================================
Provides a single, reusable function to create an authenticated
Elasticsearch client for all pipeline scripts.

Supports two connection modes automatically:
  - Elastic Serverless (ELASTIC_ENDPOINT) — used in this project
  - Elastic Cloud classic (ELASTIC_CLOUD_ID) — fallback

All scripts import get_client() from here instead of creating
their own connection, ensuring credentials are managed in one place.

Usage:
    from config.elastic_client import get_client
    es = get_client()

Test your connection directly:
    python config/elastic_client.py
"""

import os
import sys
from elasticsearch import Elasticsearch
from dotenv import load_dotenv
from colorama import Fore, init

init(autoreset=True)
load_dotenv()


def get_client() -> Elasticsearch:
    """
    Create and return an authenticated Elasticsearch client.

    Reads credentials from environment variables (.env file):
        ELASTIC_ENDPOINT — full HTTPS URL for Elastic Serverless projects
        ELASTIC_CLOUD_ID — cloud ID string for classic Elastic Cloud (fallback)
        ELASTIC_API_KEY  — API key for authentication

    Returns:
        Elasticsearch: authenticated client ready for queries

    Raises:
        SystemExit: if required credentials are missing from .env
    """
    api_key  = os.getenv("ELASTIC_API_KEY")
    endpoint = os.getenv("ELASTIC_ENDPOINT")      # Serverless
    cloud_id = os.getenv("ELASTIC_CLOUD_ID")      # Traditional Cloud (fallback)

    if not api_key:
        print(Fore.RED + """
ERROR: ELASTIC_API_KEY not set in .env

How to get it:
  1. Go to your Elastic project dashboard
  2. On the "Get started" page, copy the API key shown
  3. Paste it into your .env file as:
     ELASTIC_API_KEY=your-full-key-here
        """)
        sys.exit(1)

    # Serverless uses endpoint URL (what you have)
    if endpoint:
        client = Elasticsearch(
            hosts=[endpoint],
            api_key=api_key,
            request_timeout=60,
            retry_on_timeout=True,
            max_retries=3
        )
        print(Fore.GREEN + f"  Elastic client ready (Serverless): {endpoint[:55]}...")
        return client

    # Fallback: traditional Elastic Cloud with cloud_id
    if cloud_id:
        client = Elasticsearch(
            cloud_id=cloud_id,
            api_key=api_key,
            request_timeout=60,
            retry_on_timeout=True,
            max_retries=3
        )
        print(Fore.GREEN + f"  Elastic client ready (Cloud ID)")
        return client

    print(Fore.RED + """
ERROR: Neither ELASTIC_ENDPOINT nor ELASTIC_CLOUD_ID is set in .env

Since you are using Elastic Serverless, set:
  ELASTIC_ENDPOINT=https://your-project.es.us-east-1.aws.elastic.cloud

Find this on your Elastic dashboard "Get started" page.
    """)
    sys.exit(1)


def test_connection() -> bool:
    """
    Run a quick ping to verify credentials and connectivity.

    Returns:
        bool: True if connection succeeds, False otherwise
    """
    try:
        es   = get_client()
        info = es.info()
        print(Fore.GREEN + f"  Connected — Elasticsearch {info['version']['number']}")
        return True
    except Exception as e:
        print(Fore.RED + f"  Connection failed: {e}")
        return False


if __name__ == "__main__":
    # Run directly to test your connection:
    # python config/elastic_client.py
    print("\n── Testing Elastic connection \n")
    ok = test_connection()
    if ok:
        print(Fore.GREEN + "\n  Elastic credentials are working correctly.\n")
    else:
        print(Fore.RED + "\n  Connection failed. Check .env file.\n")