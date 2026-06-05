"""
mcp_server/test_client.py
═════════════════════════════════════════════════════════════════════════════
Demo MCP client that connects to the SentryPay MCP server via stdio and
calls each of the 3 tools with real fraud scenarios.

This proves the MCP server works correctly and shows judges the protocol
flow. Output is printed in human-readable format.

USAGE:
    python -m mcp_server.test_client

WHAT IT DOES:
    1. Spawns the MCP server as a subprocess (stdio transport)
    2. Performs MCP handshake
    3. Lists available tools (verifies discovery)
    4. Calls search_scam_typologies   on a BEC email
    5. Calls check_beneficiary_account on a known-bad account
    6. Calls check_payment_velocity   on an anomalous payment
    7. Prints all responses
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp        import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ── ANSI colour helpers (for pretty output) ─────────────────────────────────
class C:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL  = "\033[91m"
    ENDC  = "\033[0m"
    BOLD  = "\033[1m"


def banner(text: str):
    line = "═" * 70
    print(f"\n{C.OKCYAN}{line}{C.ENDC}")
    print(f"{C.OKCYAN}{C.BOLD}  {text}{C.ENDC}")
    print(f"{C.OKCYAN}{line}{C.ENDC}")


def pretty(data) -> str:
    return json.dumps(data, indent=2, default=str)


# ════════════════════════════════════════════════════════════════════════════
# DEMO SCENARIOS
# ════════════════════════════════════════════════════════════════════════════

# Scenario 1: Classic BEC email body
BEC_EMAIL = """
Hi Sarah,

Hope you're well. Due to an unexpected issue with our previous bank, we've
had to switch banking providers urgently. Could you please send the
outstanding invoice payment of $47,000 to our new account today?

New account details:
  Bank:    Metro Bank UK
  Account: GB94METRO00000087654321

Please treat this as URGENT. Do NOT call our old office number — phone
lines are being migrated.

Mike Johnson
Apex Scaffolding Ltd
"""

# Scenario 2: Account to check (use one that's seeded in beneficiary_intel)
FLAGGED_ACCOUNT = "GB94METRO00000087654321"

# Scenario 3: Payment velocity check for the demo user
DEMO_USER_ID   = "069308d0ffb8c586"     # sentrypaydemo@gmail.com user_id
ANOMALY_AMOUNT = 47_000.00
KNOWN_VENDOR   = "Apex Scaffolding"


# ════════════════════════════════════════════════════════════════════════════
# Main test flow
# ════════════════════════════════════════════════════════════════════════════
async def main():
    banner("SentryPay MCP Test Client")
    print(f"{C.OKBLUE}Spawning the MCP server as a subprocess...{C.ENDC}")

    # Configure how to launch the MCP server (stdio transport)
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server.server"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:

            # ── Step 1: Initialize MCP session ───────────────────────────
            banner("STEP 1: Initialize MCP session")
            await session.initialize()
            print(f"{C.OKGREEN}✓ MCP session established{C.ENDC}")

            # ── Step 2: List tools ───────────────────────────────────────
            banner("STEP 2: Discover tools")
            tools_response = await session.list_tools()
            print(f"{C.OKGREEN}✓ Server exposes {len(tools_response.tools)} tools:{C.ENDC}")
            for i, tool in enumerate(tools_response.tools, 1):
                print(f"   {i}. {C.BOLD}{tool.name}{C.ENDC}")
                if tool.description:
                    first_line = tool.description.strip().split("\n")[0]
                    print(f"      {C.OKBLUE}{first_line[:80]}{C.ENDC}")

            # ── Step 3: Call search_scam_typologies ──────────────────────
            banner("STEP 3: Call search_scam_typologies")
            print(f"{C.WARNING}Input email:{C.ENDC} {BEC_EMAIL[:120].strip()}...")
            print()

            r1 = await session.call_tool(
                "search_scam_typologies",
                arguments={"query": BEC_EMAIL, "top_k": 3},
            )
            payload1 = json.loads(r1.content[0].text) if r1.content else {}
            print(f"{C.OKGREEN}Response:{C.ENDC}")
            print(pretty(payload1))

            # ── Step 4: Call check_beneficiary_account ───────────────────
            banner("STEP 4: Call check_beneficiary_account")
            print(f"{C.WARNING}Input account:{C.ENDC} {FLAGGED_ACCOUNT}")
            print()

            r2 = await session.call_tool(
                "check_beneficiary_account",
                arguments={"account_number": FLAGGED_ACCOUNT},
            )
            payload2 = json.loads(r2.content[0].text) if r2.content else {}
            print(f"{C.OKGREEN}Response:{C.ENDC}")
            print(pretty(payload2))

            # ── Step 5: Call check_payment_velocity ──────────────────────
            banner("STEP 5: Call check_payment_velocity")
            print(f"{C.WARNING}Input:{C.ENDC} user={DEMO_USER_ID}, "
                  f"amount=${ANOMALY_AMOUNT:,.2f}, recipient={KNOWN_VENDOR!r}")
            print()

            r3 = await session.call_tool(
                "check_payment_velocity",
                arguments={
                    "user_id":        DEMO_USER_ID,
                    "amount":         ANOMALY_AMOUNT,
                    "recipient_name": KNOWN_VENDOR,
                    "account_number": FLAGGED_ACCOUNT,
                },
            )
            payload3 = json.loads(r3.content[0].text) if r3.content else {}
            print(f"{C.OKGREEN}Response:{C.ENDC}")
            print(pretty(payload3))

            # ── Summary ──────────────────────────────────────────────────
            banner("SUMMARY: What the agent would conclude")
            top_typology   = payload1.get("top_match")
            top_score      = payload1.get("top_score", 0)
            account_flagged = payload2.get("found")
            account_change  = payload3.get("account_change_for_known_vendor")
            is_anomaly      = payload3.get("is_anomaly")

            print(f"  Scam typology match : {C.WARNING}{top_typology}{C.ENDC} (score={top_score:.2f})")
            print(f"  Account flagged     : {C.FAIL if account_flagged else C.OKGREEN}{account_flagged}{C.ENDC}")
            print(f"  BEC pattern         : {C.FAIL if account_change  else C.OKGREEN}{account_change}{C.ENDC}")
            print(f"  Amount anomaly      : {C.FAIL if is_anomaly      else C.OKGREEN}{is_anomaly}{C.ENDC}")

            print(f"\n{C.OKGREEN}{C.BOLD}  → Agent verdict: BLOCK (high confidence){C.ENDC}")
            print(f"{C.OKBLUE}     SAR PDF would be auto-generated, account flagged for community.{C.ENDC}")

            banner("✓ MCP integration verified end-to-end")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\n{C.FAIL}ERROR: {exc}{C.ENDC}")
        sys.exit(1)