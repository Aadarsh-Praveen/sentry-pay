"""
mcp_server/server.py
═════════════════════════════════════════════════════════════════════════════
SentryPay MCP Server — exposes Elastic-backed fraud detection tools via the
Model Context Protocol (MCP).

THREE TOOLS:
  1. search_scam_typologies     — kNN vector search against 306 known fraud patterns
  2. check_beneficiary_account  — direct lookup against 68k flagged accounts
  3. check_payment_velocity     — anomaly detection vs user's behavioural baseline

ARCHITECTURE:
    Gemini Agent
         │
         ▼
   [MCP Protocol]
         │
         ▼
   FastMCP Server (this file)
         │
         ▼
   Elasticsearch Serverless
   (5 indices: scam_typologies, beneficiary_intel,
    customer_transactions, user_baselines, email_verdicts)

USAGE:
    # Run in stdio mode (for Claude Desktop / MCP clients):
    python -m mcp_server.server

    # Run in HTTP / SSE mode (for remote agents, Cloud Run):
    python -m mcp_server.server --http --port 9000

    # Test it via the demo client:
    python -m mcp_server.test_client
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Make project root importable so we can use the same Elastic client
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from config.elastic_client import get_client as _raw_get_client

load_dotenv()


def get_client():
    """
    Wrap config.elastic_client.get_client so that:
      1. Missing credentials surface as a normal exception instead of
         `sys.exit(1)` (which would kill the whole MCP server process
         mid-request). MCP tools catch `Exception` but not `SystemExit`.
      2. Any stdout prints from the upstream client (e.g. "Elastic client
         ready (Serverless): ...") are redirected to stderr — in stdio mode,
         stdout is reserved for JSON-RPC frames.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            return _raw_get_client()
    except SystemExit as exc:
        raise RuntimeError(
            "Elastic client unavailable — check ELASTIC_API_KEY and "
            "ELASTIC_ENDPOINT (or ELASTIC_CLOUD_ID) in your .env file."
        ) from exc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [mcp] %(message)s")
log = logging.getLogger("sentrypay-mcp")

# ─────────────────────────────────────────────────────────────────────────────
# MCP server instance
# ─────────────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="sentrypay",
    instructions=(
        "SentryPay MCP server. Provides three Elastic-backed tools for payment "
        "fraud detection: search_scam_typologies for matching known fraud "
        "patterns via vector search, check_beneficiary_account for querying a "
        "database of flagged accounts, and check_payment_velocity for "
        "detecting amount/vendor anomalies against a user's behavioural baseline."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# Vertex AI embedding helper (for scam typology vector search)
# ─────────────────────────────────────────────────────────────────────────────
_embedding_model = None


def _embed_query(text: str) -> list[float]:
    """Embed text using Vertex AI text-embedding-004 (768-dim)."""
    global _embedding_model
    if _embedding_model is None:
        from vertexai.language_models import TextEmbeddingModel
        import vertexai
        vertexai.init(
            project=os.getenv("GCP_PROJECT_ID"),
            location=os.getenv("GCP_REGION", "us-central1"),
        )
        model_name = os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-004")
        _embedding_model = TextEmbeddingModel.from_pretrained(model_name)

    embeddings = _embedding_model.get_embeddings([text])
    return embeddings[0].values


# ═════════════════════════════════════════════════════════════════════════════
# TOOL 1 — search_scam_typologies
# ═════════════════════════════════════════════════════════════════════════════
@mcp.tool()
def search_scam_typologies(query: str, top_k: int = 3) -> dict:
    """
    Semantic search against the scam_typologies index using kNN vector search.

    Returns the top_k known fraud patterns most similar to the input query text
    (typically the body of a suspicious payment email).

    Args:
        query:  The text to search against (e.g. email body excerpt).
        top_k:  Number of matches to return (default 3, max 10).

    Returns:
        {
          "matches": [
            {
              "typology_id": str,
              "name":        str,        # e.g. "Business Email Compromise"
              "description": str,
              "score":       float,      # cosine similarity 0-1
              "indicators":  [str],      # keyword patterns
              "loss_avg_usd": float
            }, ...
          ],
          "top_match":  str | None,      # name of #1 match (None if no matches)
          "top_score":  float            # score of #1 match
        }
    """
    top_k = max(1, min(top_k, 10))

    try:
        es = get_client()
        embedding = _embed_query(query)

        response = es.search(
            index="scam_typologies",
            knn={
                "field":          "embedding",
                "query_vector":   embedding,
                "k":              top_k,
                "num_candidates": 50,
            },
            size=top_k,
        )

        matches = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            matches.append({
                "typology_id":  src.get("typology_id"),
                "name":         src.get("name"),
                "description":  (src.get("description") or "")[:300],
                "score":        round(hit["_score"], 4),
                "indicators":   src.get("indicators", [])[:10],
                "loss_avg_usd": src.get("loss_avg_usd", 0),
            })

        log.info(f"search_scam_typologies(query={query[:40]!r}) → "
                 f"{len(matches)} matches, top={matches[0]['name'] if matches else 'None'}")

        return {
            "matches":   matches,
            "top_match": matches[0]["name"]   if matches else None,
            "top_score": matches[0]["score"]  if matches else 0.0,
        }

    except Exception as exc:
        log.error(f"search_scam_typologies failed: {exc}")
        return {"matches": [], "top_match": None, "top_score": 0.0, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# TOOL 2 — check_beneficiary_account
# ═════════════════════════════════════════════════════════════════════════════
@mcp.tool()
def check_beneficiary_account(account_number: str) -> dict:
    """
    Check whether a beneficiary account is in SentryPay's flagged-accounts
    database (built from OpenSanctions, FinCEN, and community-flagged fraud).

    Args:
        account_number:  IBAN, routing+account, or similar identifier.

    Returns:
        {
          "found":          bool,         # whether the account is flagged
          "risk_score":     float,        # 0-1 (1 = highest risk)
          "flag_reasons":   [str],        # why it was flagged
          "case_count":     int,          # how many prior cases
          "first_flagged":  str | None,   # ISO date
        }
    """
    if not account_number or len(account_number) < 4:
        return {
            "found":         False,
            "risk_score":    0.0,
            "flag_reasons":  [],
            "case_count":    0,
            "first_flagged": None,
            "error":         "Account number too short",
        }

    try:
        es = get_client()
        response = es.search(
            index="beneficiary_intel",
            query={"term": {"account_number": account_number}},
            size=1,
        )

        hits = response["hits"]["hits"]
        if not hits:
            log.info(f"check_beneficiary_account({account_number[-6:]}) → not flagged")
            return {
                "found":         False,
                "risk_score":    0.0,
                "flag_reasons":  [],
                "case_count":    0,
                "first_flagged": None,
            }

        src = hits[0]["_source"]
        log.warning(f"check_beneficiary_account({account_number[-6:]}) → FLAGGED "
                    f"(risk={src.get('risk_score', 0):.2f})")

        return {
            "found":         True,
            "risk_score":    float(src.get("risk_score", 0)),
            "flag_reasons":  src.get("flag_reasons", []),
            "case_count":    int(src.get("case_count", 1)),
            "first_flagged": src.get("first_flagged"),
        }

    except Exception as exc:
        log.error(f"check_beneficiary_account failed: {exc}")
        return {
            "found":         False,
            "risk_score":    0.0,
            "flag_reasons":  [],
            "case_count":    0,
            "first_flagged": None,
            "error":         str(exc),
        }


# ═════════════════════════════════════════════════════════════════════════════
# TOOL 3 — check_payment_velocity
# ═════════════════════════════════════════════════════════════════════════════
@mcp.tool()
def check_payment_velocity(
    user_id:        str,
    amount:         float,
    recipient_name: str = "",
    account_number: str = "",
) -> dict:
    """
    Compare a proposed payment against the user's historical baseline to detect
    amount anomalies, unknown vendors, and account-change patterns characteristic
    of Business Email Compromise (BEC).

    Args:
        user_id:        User identifier.
        amount:         Proposed payment amount in USD.
        recipient_name: Recipient/vendor name (for known-vendor check).
        account_number: Destination account (for known-account check).

    Returns:
        {
          "baseline_exists":   bool,
          "mean_payment":      float,    # user's average payment size
          "max_normal":        float,    # IQR upper-fence threshold
          "current_amount":    float,
          "deviation_factor":  float,    # current / mean
          "is_anomaly":        bool,     # current > max_normal
          "known_vendor":      bool,
          "known_account":     bool,
          "account_change_for_known_vendor": bool,   # CRITICAL: BEC indicator
        }
    """
    try:
        es = get_client()
        baseline_resp = es.get(index="user_baselines", id=user_id, ignore=[404])

        if not baseline_resp.get("found"):
            log.info(f"check_payment_velocity(user={user_id}) → no baseline yet")
            return {
                "baseline_exists":  False,
                "mean_payment":     0.0,
                "max_normal":       10_000.0,   # conservative default
                "current_amount":   amount,
                "deviation_factor": 0.0,
                "is_anomaly":       amount > 10_000,
                "known_vendor":     False,
                "known_account":    False,
                "account_change_for_known_vendor": False,
            }

        baseline       = baseline_resp["_source"]
        mean_payment   = float(baseline.get("mean_payment",   0))
        max_normal     = float(baseline.get("max_normal", 10_000))
        known_vendors  = baseline.get("known_vendors",  []) or []
        known_accounts = baseline.get("known_accounts", []) or []

        # Normalize for matching (lowercase, strip)
        norm = lambda s: (s or "").lower().strip()
        recipient_norm = norm(recipient_name)
        known_vendors_norm = [norm(v) for v in known_vendors]

        is_known_vendor  = bool(recipient_norm) and any(
            recipient_norm in v or v in recipient_norm for v in known_vendors_norm
        )
        is_known_account = bool(account_number) and (account_number in known_accounts)

        deviation = (amount / mean_payment) if mean_payment > 0 else 0.0
        is_anomaly = amount > max_normal

        # CRITICAL signal: known vendor at unknown account = vendor banking change
        account_change_for_known_vendor = is_known_vendor and (not is_known_account)

        result = {
            "baseline_exists":  True,
            "mean_payment":     round(mean_payment,   2),
            "max_normal":       round(max_normal,     2),
            "current_amount":   round(amount,         2),
            "deviation_factor": round(deviation,      2),
            "is_anomaly":       is_anomaly,
            "known_vendor":     is_known_vendor,
            "known_account":    is_known_account,
            "account_change_for_known_vendor": account_change_for_known_vendor,
        }
        log.info(f"check_payment_velocity(user={user_id}, ${amount:.2f}) → "
                 f"anomaly={is_anomaly}, known_vendor={is_known_vendor}, "
                 f"known_account={is_known_account}, bec_pattern={account_change_for_known_vendor}")
        return result

    except Exception as exc:
        log.error(f"check_payment_velocity failed: {exc}")
        return {
            "baseline_exists":  False,
            "mean_payment":     0.0,
            "max_normal":       10_000.0,
            "current_amount":   amount,
            "deviation_factor": 0.0,
            "is_anomaly":       False,
            "known_vendor":     False,
            "known_account":    False,
            "account_change_for_known_vendor": False,
            "error":            str(exc),
        }


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="SentryPay MCP server")
    parser.add_argument("--http",  action="store_true",
                        help="Run in HTTP/SSE mode instead of stdio")
    parser.add_argument("--port",  type=int, default=9000,
                        help="Port for HTTP mode (default 9000)")
    args = parser.parse_args()

    # In stdio mode, stdout is reserved for JSON-RPC frames — any stray text
    # there corrupts the MCP stream and the client logs ParseError tracebacks.
    # Print the banner to stderr in stdio mode, stdout in HTTP mode.
    out = sys.stdout if args.http else sys.stderr

    print("", file=out)
    print("╔══════════════════════════════════════════════════════════════╗", file=out)
    print("║          SentryPay MCP Server — Elastic Track                ║", file=out)
    print("╠══════════════════════════════════════════════════════════════╣", file=out)
    print("║  Tools exposed:                                              ║", file=out)
    print("║    1. search_scam_typologies   (kNN vector search)           ║", file=out)
    print("║    2. check_beneficiary_account (structured lookup)          ║", file=out)
    print("║    3. check_payment_velocity    (per-user aggregations)      ║", file=out)
    print("╚══════════════════════════════════════════════════════════════╝", file=out)
    print("", file=out)

    if args.http:
        # FastMCP SSE binds 0.0.0.0:8000 by default; override with env
        os.environ["FASTMCP_PORT"] = str(args.port)
        print(f"Starting in HTTP/SSE mode on port {args.port}...", file=out)
        mcp.run(transport="sse")
    else:
        print("Starting in stdio mode (for MCP clients like Claude Desktop)...", file=out)
        print("Pipe via MCP — no HTTP endpoint.", file=out)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()