"""
SentryPay — Agent Tools
========================
Defines the three tool functions that the Gemini agent calls when
analysing a payment request. Each tool queries a specific Elasticsearch
index and returns structured results that Gemini uses to reason about
whether a payment is fraudulent.

The three tools map directly to the three checks the agent performs:

  Tool 1 — search_scam_typologies:
      Performs a hybrid vector + keyword search against the
      scam_typologies index. Converts the incoming email text to a
      vector embedding and finds the most semantically similar known
      fraud patterns. Answers the question: "Does this email match
      a known scam pattern?"

  Tool 2 — check_beneficiary_account:
      Runs an ES|QL query against the beneficiary_intel index to
      retrieve the risk score and flag status of the destination
      account. Answers the question: "Is this account flagged?"

  Tool 3 — check_payment_velocity:
      Runs an ES|QL query against customer_transactions and
      user_baselines to compare the incoming payment against the
      user's historical behaviour. Answers the question: "Is this
      payment unusual for this user?"

These functions are registered as callable tools in the Gemini agent.
Gemini decides which tools to call and in what order based on the
evidence it still needs to reach a decision.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import vertexai
from vertexai.language_models import TextEmbeddingModel

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.elastic_client import get_client

load_dotenv()

# ── Retry decorator ───────────────────────────────────────────────────────────

def with_retry(max_attempts: int = 3, delay_seconds: float = 2.0):
    """
    Retry a tool function on transient network failures.
    Retries with exponential backoff on ConnectionError, TimeoutError, OSError.
    """
    import functools
    import time as _time

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, TimeoutError, OSError) as e:
                    last_error = e
                    if attempt < max_attempts:
                        wait = delay_seconds * (2 ** (attempt - 1))
                        print(f"  ⚠ Retry {attempt}/{max_attempts} in {wait:.0f}s: {e}")
                        _time.sleep(wait)
                    else:
                        print(f"  ✗ Failed after {max_attempts} attempts: {e}")
                except Exception:
                    raise
            return {"error": str(last_error), "retry_exhausted": True}
        return wrapper
    return decorator


GCP_PROJECT = os.getenv("GCP_PROJECT_ID")
GCP_REGION  = os.getenv("GCP_REGION", "us-central1")

# Initialise shared resources once at module load
vertexai.init(project=GCP_PROJECT, location=GCP_REGION)
_embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")
_es              = get_client()


# ── Tool 1 — Scam Typology Search ────────────────────────────────────────────

@with_retry(max_attempts=3, delay_seconds=2.0)
def search_scam_typologies(email_text: str, payment_context: str) -> dict:
    """
    Perform a semantic vector search to find fraud patterns that match
    the submitted email and payment context.

    Combines the email text and payment context into a single string,
    converts it to a 768-dimensional embedding using text-embedding-004,
    then runs a k-nearest-neighbour search against the scam_typologies
    index to find the most semantically similar known fraud patterns.

    Args:
        email_text (str): the suspicious email or message text submitted
                          by the user
        payment_context (str): payment details including amount, recipient
                               name, and payment type

    Returns:
        dict: containing:
              - matches (list): top 3 matching typologies, each with
                typology_name, description, red_flags, similarity_score
              - top_match (str): name of the closest matching typology
              - top_score (float): cosine similarity of the top match
                (0.0 = no similarity, 1.0 = identical meaning)
              - search_successful (bool): False if the query failed
    """
    try:
        combined_text = f"{email_text} | Payment: {payment_context}"
        embedding     = _embedding_model.get_embeddings([combined_text])[0].values

        result = _es.search(
            index="scam_typologies",
            body={
                "knn": {
                    "field":          "description_vector",
                    "query_vector":   embedding,
                    "k":              3,
                    "num_candidates": 50
                },
                "_source": ["typology_name", "description", "red_flags",
                            "target_victim", "typical_payment_type", "avg_loss_usd"],
                "size": 3
            }
        )

        hits    = result['hits']['hits']
        matches = []

        for hit in hits:
            matches.append({
                "typology_name":      hit['_source'].get('typology_name'),
                "description":        hit['_source'].get('description'),
                "red_flags":          hit['_source'].get('red_flags', []),
                "target_victim":      hit['_source'].get('target_victim'),
                "typical_payment":    hit['_source'].get('typical_payment_type'),
                "avg_loss_usd":       hit['_source'].get('avg_loss_usd', 0),
                "similarity_score":   round(hit['_score'], 4)
            })

        return {
            "matches":          matches,
            "top_match":        matches[0]['typology_name'] if matches else None,
            "top_score":        matches[0]['similarity_score'] if matches else 0.0,
            "search_successful": True
        }

    except Exception as e:
        return {
            "matches":           [],
            "top_match":         None,
            "top_score":         0.0,
            "search_successful": False,
            "error":             str(e)
        }


# ── Tool 2 — Beneficiary Account Check ───────────────────────────────────────

@with_retry(max_attempts=3, delay_seconds=2.0)
def check_beneficiary_account(account_number: str, recipient_name: str) -> dict:
    """
    Query the beneficiary_intel index to score the risk of a destination
    account using ES|QL.

    Looks up the exact account number in the beneficiary_intel index and
    returns its risk score, flag status, and reason for flagging (if any).
    Also checks whether the recipient name matches the name associated
    with the account, as a name/account mismatch is a strong fraud signal.

    Args:
        account_number (str): the destination bank account number
        recipient_name (str): the name of the payment recipient as
                               stated in the email or payment form

    Returns:
        dict: containing:
              - is_flagged (bool): True if account appears in flagged list
              - risk_score (float): 0.0 (clean) to 1.0 (high risk)
              - risk_category (str): LOW / MEDIUM / HIGH
              - flag_reason (str): why the account is flagged, if applicable
              - account_found (bool): False if account not in database
              - name_match (bool): whether recipient_name matches records
    """
    try:
        result = _es.esql.query(body={
            "query": f"""
                FROM beneficiary_intel
                | WHERE account_number == "{account_number}"
                | KEEP entity_name, risk_score, risk_category,
                        flag_reason, is_flagged, datasets
                | LIMIT 1
            """
        })

        rows = result.get('values', [])

        if not rows:
            # Account not found — unknown, assign low-medium default risk
            return {
                "is_flagged":     False,
                "risk_score":     0.20,
                "risk_category":  "UNKNOWN",
                "flag_reason":    "Account not found in database — new or unverified",
                "account_found":  False,
                "name_match":     None
            }

        cols        = result.get('columns', [])
        col_names   = [c['name'] for c in cols]
        row         = dict(zip(col_names, rows[0]))

        # Check if recipient name matches the account holder
        db_name    = str(row.get('entity_name', '')).lower()
        input_name = recipient_name.lower()
        name_match = (
            input_name in db_name or
            db_name in input_name or
            any(word in db_name for word in input_name.split() if len(word) > 3)
        )

        return {
            "is_flagged":    bool(row.get('is_flagged', False)),
            "risk_score":    float(row.get('risk_score', 0.0)),
            "risk_category": str(row.get('risk_category', 'LOW')),
            "flag_reason":   str(row.get('flag_reason', '')),
            "account_found": True,
            "name_match":    name_match
        }

    except Exception as e:
        return {
            "is_flagged":    False,
            "risk_score":    0.15,
            "risk_category": "UNKNOWN",
            "flag_reason":   f"Query failed: {str(e)}",
            "account_found": False,
            "name_match":    None
        }


# ── Tool 3 — Payment Velocity Check ──────────────────────────────────────────

@with_retry(max_attempts=3, delay_seconds=2.0)
def check_payment_velocity(user_id: str, amount: float,
                           recipient_name: str, account_number: str,
                           payment_type: str) -> dict:
    """
    Compare the incoming payment against the user's historical behaviour
    to detect anomalies using ES|QL queries.

    Queries the user_baselines index for the user's pre-computed
    behavioural profile (mean payment, standard deviation, known accounts)
    and compares the incoming payment against these baselines to produce
    anomaly signals.

    Anomaly signals checked:
        - Amount vs max_normal threshold (IQR upper fence)
        - Amount expressed as a z-score (standard deviations from mean)
        - Whether the destination account has been paid before
        - Whether the recipient name is known to this user

    Args:
        user_id (str): identifier of the user making the payment
        amount (float): the payment amount in USD
        recipient_name (str): name of the payment recipient
        account_number (str): destination account number
        payment_type (str): ACH / Wire / RTP / Zelle / Check

    Returns:
        dict: containing:
              - is_amount_anomalous (bool): True if amount > max_normal
              - z_score (float): how many std deviations from the mean
              - is_new_account (bool): True if never paid before
              - is_new_vendor (bool): True if vendor name is unknown
              - user_mean (float): user's average payment amount
              - user_max_normal (float): IQR upper anomaly threshold
              - anomaly_count (int): number of anomaly signals triggered (0-4)
    """
    try:
        # Get user baseline
        baseline_result = _es.esql.query(body={
            "query": f"""
                FROM user_baselines
                | WHERE user_id == "{user_id}"
                | KEEP mean_payment, std_payment, max_normal,
                        known_accounts, known_vendors, preferred_rail
                | LIMIT 1
            """
        })

        rows = baseline_result.get('values', [])

        if not rows:
            # No baseline — new user, flag as unknown
            return {
                "is_amount_anomalous": False,
                "z_score":             0.0,
                "is_new_account":      True,
                "is_new_vendor":       True,
                "user_mean":           0.0,
                "user_max_normal":     0.0,
                "anomaly_count":       1,
                "note":                "No baseline found for this user"
            }

        cols      = baseline_result.get('columns', [])
        col_names = [c['name'] for c in cols]
        row       = dict(zip(col_names, rows[0]))

        mean_payment    = float(row.get('mean_payment', 0))
        std_payment     = float(row.get('std_payment', 1))
        max_normal      = float(row.get('max_normal', 0))
        known_accounts  = row.get('known_accounts', []) or []
        known_vendors   = row.get('known_vendors', []) or []

        # Compute anomaly signals
        is_amount_anomalous = amount > max_normal
        z_score = round((amount - mean_payment) / max(std_payment, 1), 2)
        is_new_account = account_number not in known_accounts
        is_new_vendor  = not any(
            v.lower() in recipient_name.lower() or
            recipient_name.lower() in v.lower()
            for v in known_vendors
        )

        # Count how many signals are triggered
        anomaly_count = sum([
            is_amount_anomalous,
            z_score > 3.0,
            is_new_account,
            is_new_vendor
        ])

        return {
            "is_amount_anomalous": is_amount_anomalous,
            "z_score":             z_score,
            "is_new_account":      is_new_account,
            "is_new_vendor":       is_new_vendor,
            "user_mean":           round(mean_payment, 2),
            "user_max_normal":     round(max_normal, 2),
            "anomaly_count":       anomaly_count
        }

    except Exception as e:
        return {
            "is_amount_anomalous": False,
            "z_score":             0.0,
            "is_new_account":      True,
            "is_new_vendor":       True,
            "user_mean":           0.0,
            "user_max_normal":     0.0,
            "anomaly_count":       1,
            "error":               str(e)
        }