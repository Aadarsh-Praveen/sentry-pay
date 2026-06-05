# SentryPay MCP Server

This directory contains the **Model Context Protocol (MCP) server** for SentryPay's
Elastic-backed fraud detection tools. It exposes three tools that any MCP-compatible
agent (Claude Desktop, Cursor, ADK, Gemini agents, etc.) can call to perform
fraud analysis grounded in real-time Elastic data.

## Why MCP?

The Google Cloud Rapid Agent Hackathon requires partner integration via
**Model Context Protocol (MCP)**. SentryPay's MCP server lets any agent
in the ecosystem (not just our Gemini agent) reuse the same fraud
intelligence — cross-vendor sanctions data, vector-matched fraud typologies,
and per-user behavioural baselines.

## Architecture

```
┌──────────────────────────────────────────────┐
│           ANY MCP-COMPATIBLE AGENT           │
│  (Gemini, Claude Desktop, Cursor, ADK, ...)  │
└─────────────────────┬────────────────────────┘
                      │ MCP protocol
                      │  (stdio or SSE/HTTP)
                      ▼
┌──────────────────────────────────────────────┐
│         SentryPay MCP Server                 │
│         (mcp_server/server.py)               │
│                                              │
│   Tools:                                     │
│   1. search_scam_typologies                  │
│   2. check_beneficiary_account               │
│   3. check_payment_velocity                  │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│        Elasticsearch Serverless              │
│   5 indices:                                 │
│   • scam_typologies      (306 docs, kNN)     │
│   • beneficiary_intel    (68k flagged accts) │
│   • customer_transactions(user payments)     │
│   • user_baselines       (per-user profiles) │
│   • email_verdicts       (audit trail)       │
└──────────────────────────────────────────────┘
```

## The Three Tools

### 1. `search_scam_typologies(query, top_k=3)`
**kNN vector search** against 306 known fraud patterns
(Business Email Compromise, romance scams, fake invoices, etc.).
Uses Vertex AI `text-embedding-004` (768-dim) for embedding,
then cosine similarity over Elastic's `dense_vector` field.

### 2. `check_beneficiary_account(account_number)`
**Structured term-search** against 68,564 flagged accounts
sourced from OpenSanctions, FinCEN, and community-flagged fraud.

### 3. `check_payment_velocity(user_id, amount, recipient_name, account_number)`
**Aggregated lookup** against the user's behavioural baseline.
Detects amount anomalies, unknown vendors, and the critical
**account-change-for-known-vendor** pattern that signals BEC.

## Running

### Prerequisites
```bash
pip install "mcp[cli]>=1.0.0"
```

Make sure your `.env` has `ELASTIC_ENDPOINT`, `ELASTIC_API_KEY`, `GCP_PROJECT_ID`.

### Mode 1 — stdio (default; for Claude Desktop / VS Code MCP / Cursor)

```bash
python -m mcp_server.server
```

To register with Claude Desktop, add this to your
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sentrypay": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd":  "/absolute/path/to/sentry-pay"
    }
  }
}
```

Then in Claude Desktop, you'll see all 3 SentryPay tools available
and Claude can call them directly to analyse payments.

### Mode 2 — HTTP/SSE (for remote agents or Cloud Run)

```bash
python -m mcp_server.server --http --port 9000
```

Then connect from any HTTP-aware MCP client to `http://localhost:9000/sse`.

## Testing

The included test client spawns the server, performs the MCP handshake,
calls each of the 3 tools with a realistic BEC scenario, and prints the
results:

```bash
python -m mcp_server.test_client
```

Expected output (abridged):

```
STEP 1: Initialize MCP session
✓ MCP session established

STEP 2: Discover tools
✓ Server exposes 3 tools:
   1. search_scam_typologies
   2. check_beneficiary_account
   3. check_payment_velocity

STEP 3: Call search_scam_typologies
{
  "matches": [
    { "name": "Business Email Compromise — Vendor Banking Change", ... }
  ],
  "top_match": "Business Email Compromise — Vendor Banking Change",
  "top_score": 0.91
}

...

SUMMARY: What the agent would conclude
  Scam typology match : Business Email Compromise (score=0.91)
  Account flagged     : True
  BEC pattern         : True
  Amount anomaly      : True

  → Agent verdict: BLOCK (high confidence)
```

## Why This Architecture Matters For The Hackathon

1. **Partner-native integration**  
   The MCP server is the canonical way to expose Elastic-backed tools
   to agents. SentryPay's three tools become reusable by any agent in the
   ecosystem.

2. **Composable with other MCP servers**  
   An agent could combine SentryPay's fraud tools with a GitLab MCP
   (for committing SAR reports) or a Slack MCP (for alerting compliance).

3. **Production-grade observability**  
   Each MCP call is logged with arguments, timing, and result — exactly
   what we already do via Langfuse for our Gemini agent.

4. **Cross-channel correlation in one substrate**  
   All 5 Elastic indices live in a single serverless project. The MCP
   server gives agents a unified view: typologies, accounts, transactions,
   baselines, and audit trail all queryable through one protocol.
